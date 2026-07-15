from debank_auto import _wait_for_data


class FakePage:
    def __init__(self):
        self.timeouts = []

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def wait_for_selector(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, timeout_ms):
        self.timeouts.append(timeout_ms)


def test_wait_for_data_has_no_fixed_hydration_delay_by_default():
    page = FakePage()

    _wait_for_data(page)

    assert page.timeouts == []


def test_wait_for_data_supports_optional_hydration_delay():
    page = FakePage()

    _wait_for_data(page, hydration_wait_ms=500)

    assert page.timeouts == [500]
