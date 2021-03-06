import urllib
import logging

from django.views.generic import FormView, TemplateView, CreateView
from django.core import signing
from django.contrib.auth import authenticate, login as auth_login
from django.shortcuts import redirect
from django.core.urlresolvers import reverse, reverse_lazy
from django.utils import timezone
from django.conf import settings

from twilio.rest.exceptions import (
    TwilioRestException,
)
from twilio.exceptions import (
    TwilioException,
)

from betterforms.forms import BetterForm

from authtools.views import LoginRequiredMixin

from ladder.apps.exchange.models import LadderProfile

from ladder.apps.accounts.forms import (
    InitiateRegistrationForm,
    UserCreationForm,
)
from ladder.apps.accounts.utils import (
    unsign_registration_token,
    send_phone_number_verification_sms,
    unsign_pre_registration_token,
)
from ladder.apps.accounts.models import User
from ladder.apps.accounts.emails import send_registration_verification_email

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/dashboard.html'


class RegistrationClosedView(TemplateView):
    template_name = 'accounts/registration-closed.html'

    def get_context_data(self, *args, **kwargs):
        context = super(RegistrationClosedView, self).get_context_data(**kwargs)
        context['registration_open_at'] = settings.REGISTRATION_OPEN_DATE
        context['registration_close_at'] = settings.REGISTRATION_CLOSE_DATE
        return context


class EnforceRegistrationWindowMixin(object):
    """
    Mixin that allows for registration outside of the allowed registration
    window with a special token, as well as enforcing the registration window.
    """
    def dispatch(self, *args, **kwargs):
        is_with_registration_window = self.is_with_registration_window()
        is_token_valid = self.is_token_valid()

        if is_token_valid or is_with_registration_window:
            return super(EnforceRegistrationWindowMixin, self).dispatch(*args, **kwargs)
        else:
            return redirect('registration-closed')

    def is_with_registration_window(self):
        open_at = settings.REGISTRATION_OPEN_DATE
        close_at = settings.REGISTRATION_CLOSE_DATE
        return open_at <= timezone.now() <= close_at

    def is_token_valid(self):
        if 'token' in self.request.GET:
            try:
                return unsign_pre_registration_token(self.request.GET['token'])
            except signing.BadSignature:
                pass
        return False


class RegisterView(EnforceRegistrationWindowMixin, FormView):
    template_name = 'accounts/register.html'
    form_class = InitiateRegistrationForm
    success_url = reverse_lazy('register-success')

    def form_valid(self, form):
        email = form.cleaned_data['email']
        if not self.is_with_registration_window():
            try:
                token_email = self.is_token_valid()
            except signing.BadSignature:
                form.form_error("Bad registration token")
                return self.form_invalid(form)
            if email != token_email:
                form.form_error(
                    "Email address does not match pre-registration token."
                )
                return self.form_invalid(form)
        phone_number = form.cleaned_data['phone_number']
        # this may be None which is ok.
        pre_registration_token = self.request.GET.get('token')
        send_registration_verification_email(
            email, phone_number, pre_registration_token=pre_registration_token,
        )
        logger.info("REGISTRATION INITIATED: %s - %s", email, phone_number)
        return super(RegisterView, self).form_valid(form)


class RegisterSuccessView(TemplateView):
    template_name = 'accounts/register_success.html'


class VerifyTokenMixin(object):
    def dispatch(self, *args, **kwargs):
        # Ensure token is valid.
        try:
            self.email, self.phone_number = unsign_registration_token(
                self.kwargs['token'],
            )
        except signing.BadSignature:
            return self.render_to_response({})
        # Ensure user does not already exist.
        try:
            User.objects.get(email__iexact=self.email)
            return self.render_to_response({'email_already_registered': True})
        except User.DoesNotExist:
            pass
        # Ensure phone_number is not taken.
        try:
            User.objects.get(_profile__phone_number=self.phone_number)
            return self.render_to_response({'phone_number_already_registered': True})
        except User.DoesNotExist:
            pass
        return super(VerifyTokenMixin, self).dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs = super(VerifyTokenMixin, self).get_context_data(**kwargs)
        kwargs.update({
            'token_valid': True,
            'token': self.kwargs['token'],
            'email': self.email,
            'phone_number': self.phone_number,
        })
        return kwargs


class RegisterConfirmView(EnforceRegistrationWindowMixin, VerifyTokenMixin, FormView):
    form_class = BetterForm
    template_name = 'accounts/register_confirm.html'

    def get_success_url(self, **kwargs):
        redirect_url = reverse('register-verify-phone-number', kwargs=self.kwargs)
        if 'token' in self.request.GET:
            redirect_url = '?'.join((
                redirect_url,
                urllib.urlencode({'token': self.request.GET['token']}),
            ))
        return redirect_url

    def form_valid(self, form):
        try:
            send_phone_number_verification_sms(self.phone_number)
        except TwilioRestException as err:
            form.add_error(None, err.msg)
            return self.form_invalid(form)
        except TwilioException:
            form.add_error(
                None,
                "Something went wrong sending your sms verification code. "
                "Either try again or contact an admin for help",
            )
            return self.form_invalid(form)
        return super(RegisterConfirmView, self).form_valid(form)


class RegisterVerifyPhoneNumberView(EnforceRegistrationWindowMixin,
                                    VerifyTokenMixin, CreateView):
    model = User
    form_class = UserCreationForm
    template_name = 'accounts/register_verify_phone_number.html'
    success_url = reverse_lazy('dashboard')

    def get_form_kwargs(self):
        kwargs = super(RegisterVerifyPhoneNumberView, self).get_form_kwargs()
        kwargs['phone_number'] = self.phone_number
        return kwargs

    def form_valid(self, form):
        # TODO: sms code verification
        form.instance.email = self.email
        form.instance.is_active = True
        self.object = user = form.save()

        LadderProfile.objects.create(
            user=user,
            phone_number=self.phone_number,
        )

        user = authenticate(
            username=user.email,
            password=form.cleaned_data['password'],
        )
        if not user:
            form.add_error(None, 'An error has occured.')
            return self.form_invalid(form)

        auth_login(self.request, user)

        logger.info("REGISTRATION COMPLETED: user:%s".format(user.pk))

        return redirect(self.success_url)
