import pytest
import mock

from django_webtest import (
    WebTest as BaseWebTest,
    DjangoTestApp as BaseDjangoTestApp,
)


@pytest.fixture()  # NOQA
def factories(transactional_db):
    import factory

    from tests.accounts.factories import (  # NOQA
        UserFactory,
        SuperUserFactory,
        SuperUserWithProfileFactory,
        UserWithProfileFactory,
    )

    from tests.exchange.factories import (  # NOQA
        LadderProfileFactory,
        TicketRequestFactory,
        TicketOfferFactory,
        TicketMatchFactory,
        AcceptedTicketMatchFactory,
        ExpiredTicketMatchFactory,
    )

    def is_factory(obj):
        if not isinstance(obj, type):
            return False
        return issubclass(obj, factory.DjangoModelFactory)

    dict_ = {k: v for k, v in locals().items() if is_factory(v)}

    return type(
        'fixtures',
        (object,),
        dict_,
    )


@pytest.fixture()  # NOQA
def models(transactional_db):
    from django.apps import apps

    dict_ = {M._meta.object_name: M for M in apps.get_models()}

    return type(
        'models',
        (object,),
        dict_,
    )


class DjangoTestApp(BaseDjangoTestApp):
    @property
    def user(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user_id = self.session.get('_auth_user_id')
        if user_id:
            return User.objects.get(pk=user_id)
        else:
            return None


class WebTest(BaseWebTest):
    app_class = DjangoTestApp

    def authenticate(self, user):
        self.app.get('/', user=user)

    def unauthenticate(self):
        self.app.get('/', user=None)


@pytest.fixture()  # NOQA
def webtest_client(transactional_db):
    web_test = WebTest(methodName='__call__')
    web_test()
    return web_test.app


@pytest.fixture()
def user_webtest_client(webtest_client, user):
    web_test = WebTest(methodName='__call__')
    web_test()
    web_test.authenticate(user)
    return web_test.app


@pytest.fixture()
def admin_webtest_client(webtest_client, admin_user):
    web_test = WebTest(methodName='__call__')
    web_test()
    web_test.authenticate(admin_user)
    return web_test.app


@pytest.fixture()  # NOQA
def User(django_user_model):
    """
    A slightly more intuitively named
    `pytest_django.fixtures.django_user_model`
    """
    return django_user_model


@pytest.fixture()
def admin_user(User):
    try:
        return User.objects.get(email='admin@example.com')
    except User.DoesNotExist:
        from django.utils import timezone
        return User.objects.create_superuser(
            last_login=timezone.now(),
            display_name='admin',
            email='admin@example.com',
            password='secret',
        )


@pytest.fixture()
def user(User):
    try:
        return User.objects.get(
            email='test@example.com',
        )
    except User.DoesNotExist:
        from django.utils import timezone
        return User.objects.create_user(
            last_login=timezone.now(),
            display_name='Test User',
            email='test@example.com',
            password='secret',
        )


@pytest.fixture()
def user_client(user, client):
    assert client.login(username=user.email, password='secret')
    client.user = user
    return client


@pytest.fixture()
def admin_client(admin_user, client):
    assert client.login(username=admin_user.email, password='secret')
    client.user = admin_user
    return client


@pytest.fixture()
def frozen_now(mocker):
    import time
    import datetime
    from django.utils import timezone

    now = timezone.datetime.now()
    now_time = time.time()
    today = datetime.date.today()

    # datetime
    mocker.patch('datetime.datetime', now=mock.Mock(return_value=now))
    mocker.patch('django.utils.timezone.now', mock.Mock(return_value=now))
    # date
    mocker.patch('datetime.date', today=mock.Mock(return_value=today))
    # time
    mocker.patch('time.time', mock.Mock(return_value=now_time))
    return now
