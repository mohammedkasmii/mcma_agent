"""The extracted NotificationService: headless-only browser, degraded
start, retry, schedule and clean stop."""

import asyncio

import pytest

import mcma.notifications.service as service_module
from central_test_support import FakeLauncher, central_settings
from mcma.notifications.service import NotificationService, NotificationServiceState


def _service(tmp_path, launcher, monkeypatch, polls, **settings_overrides):
    monkeypatch.setattr(service_module, "launch_browser", launcher)

    async def fake_poll_all_accounts(conn, browser, codes, **kwargs):
        polls.append((browser, kwargs["allowed_host"], kwargs["vault_dir"]))
        return {}

    monkeypatch.setattr(service_module, "poll_all_accounts", fake_poll_all_accounts)
    return NotificationService(
        object(), central_settings(tmp_path, **settings_overrides), crypto_backend=object()
    )


def test_start_launches_only_a_headless_browser(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(), []
    service = _service(tmp_path, launcher, monkeypatch, polls)
    assert service.state is NotificationServiceState.STARTING
    asyncio.run(service.start())
    assert service.state is NotificationServiceState.READY
    assert [browser.headless for browser in launcher.launches] == [True]


def test_first_pass_is_due_immediately_then_waits_for_the_interval(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(), []
    service = _service(tmp_path, launcher, monkeypatch, polls, notification_poll_interval_seconds=300.0)

    async def scenario():
        await service.start()
        await service.poll_if_due(2.0)   # due at start
        await service.poll_if_due(2.0)   # not due again for ~300s
        await service.poll_if_due(298.0)

    asyncio.run(scenario())
    assert len(polls) == 2
    # Notification polling reads the portal host, never the mock target.
    assert polls[0][1] == "sinauto.mamda-mcma.ma"


def test_disabled_notifications_never_poll(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(), []
    service = _service(tmp_path, launcher, monkeypatch, polls, notifications_enabled=False)
    asyncio.run(service.poll_if_due(1000.0))
    assert polls == [] and launcher.launches == []


def test_launch_failure_is_degraded_not_fatal_and_heals_on_retry(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(fail_times=1), []
    monkeypatch.setattr(service_module, "BROWSER_RETRY_SECONDS", 0.5)
    service = _service(tmp_path, launcher, monkeypatch, polls, notification_poll_interval_seconds=10.0)

    async def scenario():
        await service.start()
        assert service.state is NotificationServiceState.DEGRADED
        assert service.browser is None
        await service.poll_if_due(0.1)          # too soon to retry: nothing launched
        assert service.state is NotificationServiceState.DEGRADED and polls == []
        await service.poll_if_due(1.0)          # retry delay elapsed: relaunched
        assert service.state is NotificationServiceState.READY
        await service.poll_if_due(10.0)         # the next due pass polls with the new browser

    asyncio.run(scenario())
    assert len(polls) == 1


def test_persistent_failure_skips_polls_without_raising(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(fail_times=99), []
    service = _service(tmp_path, launcher, monkeypatch, polls)

    async def scenario():
        await service.start()
        await service.poll_if_due(1.0)
        await service.poll_if_due(100.0)   # retries fail too; nothing raises

    asyncio.run(scenario())
    assert polls == [] and service.state is NotificationServiceState.DEGRADED


def test_on_browser_ready_hook_receives_the_browser(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(), []
    monkeypatch.setattr(service_module, "launch_browser", launcher)
    seen = []
    service = NotificationService(
        object(), central_settings(tmp_path), crypto_backend=object(), on_browser_ready=seen.append
    )
    asyncio.run(service.start())
    assert seen == [service.browser]


def test_stop_closes_the_browser_and_is_idempotent(tmp_path, monkeypatch):
    launcher, polls = FakeLauncher(), []
    service = _service(tmp_path, launcher, monkeypatch, polls)

    async def scenario():
        await service.start()
        await service.stop()
        await service.stop()
        await service.start()  # a stopped service does not relaunch

    asyncio.run(scenario())
    assert launcher.launches[0].closed is True and len(launcher.launches) == 1
    assert service.state is NotificationServiceState.STOPPED and service.browser is None


def test_run_loop_survives_a_failing_pass(tmp_path, monkeypatch):
    launcher = FakeLauncher()
    monkeypatch.setattr(service_module, "launch_browser", launcher)
    calls = []

    async def flaky(conn, browser, codes, **kwargs):
        calls.append(1)
        raise RuntimeError("portal exploded")

    monkeypatch.setattr(service_module, "poll_all_accounts", flaky)
    service = NotificationService(
        object(), central_settings(tmp_path, notification_poll_interval_seconds=0.01),
        crypto_backend=object(),
    )

    async def scenario():
        task = asyncio.create_task(service.run(0.02))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.stop()

    asyncio.run(scenario())
    assert len(calls) >= 2  # kept going after the first failure
