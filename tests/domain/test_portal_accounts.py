"""Correction batch (owner amendment) -- the four shared PortalAccount
profiles: typed classification, MAMDA-is-not-MCMA, fail-closed on an
unrecognized entity/scope."""

import pytest

from mcma.domain.portal_accounts import PortalAccountProfile, PortalEntity, PortalScope, THE_FOUR_PROFILES


def test_there_are_exactly_four_canonical_profiles():
    assert len(THE_FOUR_PROFILES) == 4
    assert len({(p.entity, p.scope) for p in THE_FOUR_PROFILES}) == 4


def test_from_row_classifies_mcma_oujda():
    profile = PortalAccountProfile.from_row("MCMA", "OUJDA")
    assert profile.entity is PortalEntity.MCMA
    assert profile.scope is PortalScope.OUJDA
    assert profile.is_mcma is True


def test_from_row_classifies_mamda_as_not_mcma():
    profile = PortalAccountProfile.from_row("MAMDA", "NADOR")
    assert profile.is_mcma is False


@pytest.mark.parametrize("entity,scope", [("MCMA", "OUJDA"), ("MCMA", "NADOR"), ("MAMDA", "OUJDA"), ("MAMDA", "NADOR")])
def test_all_four_combinations_round_trip(entity, scope):
    profile = PortalAccountProfile.from_row(entity, scope)
    assert profile in THE_FOUR_PROFILES


def test_from_row_fails_closed_on_unrecognized_entity():
    with pytest.raises(ValueError):
        PortalAccountProfile.from_row("ACME", "OUJDA")


def test_from_row_fails_closed_on_unrecognized_scope():
    """The database itself deliberately leaves scope unconstrained (a
    future office must remain addable without a schema change) -- but
    this application-layer classification still fails closed rather than
    inventing a fifth handled profile."""
    with pytest.raises(ValueError):
        PortalAccountProfile.from_row("MCMA", "CASABLANCA")


def test_profile_is_frozen_and_hashable():
    profile = PortalAccountProfile.from_row("MCMA", "OUJDA")
    with pytest.raises(AttributeError):
        profile.entity = PortalEntity.MAMDA  # type: ignore[misc]
    assert hash(profile) == hash(PortalAccountProfile.from_row("MCMA", "OUJDA"))
