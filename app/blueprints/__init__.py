"""Route blueprints (auth, dashboard, marks, timetable, push, feedback, internal).

Each module holds one route table: the URL rules for its area, pointing at
the view functions in app/app.py. create_app() registers them via
FlatBlueprint, which skips Flask's `<blueprint>.<endpoint>` prefixing so
endpoints keep their pre-blueprint names (`login`, not `auth.login`) — the
url_map stays byte-identical to the flat app's (dump: scripts/url_map_dump.py;
pinned: tests/test_app_factory.py).

Entry order matters: blueprint modules import their views from app.app,
so import app.app (or anything that pulls it in) first — importing a
blueprint module on its own is a circular import.
"""
from flask.blueprints import Blueprint, BlueprintSetupState


class _FlatState(BlueprintSetupState):
    """Setup state that skips the `<blueprint>.<endpoint>` prefixing."""

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        # No url_prefix/subdomain handling by design: every OpenSRM rule is
        # absolute and unprefixed, and the url_map must stay byte-identical
        # to the flat pre-split app's (bare endpoints like `login`).
        if endpoint is None:
            endpoint = view_func.__name__
        self.app.add_url_rule(rule, endpoint, view_func,
                              defaults=self.url_defaults, **options)


class FlatBlueprint(Blueprint):
    """A Blueprint whose endpoints keep their bare names."""

    def make_setup_state(self, app, options, first_registration=False):
        return _FlatState(self, app, options, first_registration)
