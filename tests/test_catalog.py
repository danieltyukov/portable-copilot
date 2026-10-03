from sparky import catalog


def test_catalog_is_consistent():
    tags = [e.tag for e in catalog.ENTRIES]
    assert len(tags) == len(set(tags)), "duplicate tags"
    for purpose, picks in catalog.PICKS.items():
        assert purpose in catalog.PURPOSES
        for tag in picks:
            assert tag in catalog.BY_TAG, f"{tag} in PICKS[{purpose}] but not in ENTRIES"
    for e in catalog.ENTRIES:
        assert e.size_gb > 0 and e.params_b >= e.active_b > 0
        assert e.licence and e.note
        assert "\u2014" not in e.note and "\u2013" not in e.note


def test_find_ignores_latest_and_case():
    assert catalog.find("Qwen3.5:4B").tag == "qwen3.5:4b"
    assert catalog.find("glm-4.7-flash:latest").tag == "glm-4.7-flash"
    assert catalog.find("nope:1b") is None


def test_speed_follows_active_parameters():
    assert catalog.find("qwen3-coder:30b").speed == "quick"      # 3.3B active
    assert catalog.find("qwen3.5:9b").speed == "slow" or catalog.find("qwen3.5:9b").speed == "steady"
    assert catalog.find("gemma4:31b").speed == "slow"


def test_recommend_respects_memory_and_space():
    small = catalog.recommend("everyday", ram_gb=8, space_gb=30)
    assert small and all(e.ram_gb <= catalog.usable_ram(8) for e in small)
    assert small[0].tag == "qwen3.5:4b"
    big = catalog.recommend("code", ram_gb=32, space_gb=60)
    assert big[0].tag == "qwen3-coder:30b"
    tight = catalog.recommend("code", ram_gb=32, space_gb=5)
    assert all(e.size_gb <= 5 for e in tight)


def test_recommend_never_picks_dense_giants():
    for purpose in catalog.PICKS:
        for e in catalog.recommend(purpose, ram_gb=128, space_gb=500, n=20):
            assert e.speed != "slow" or e.active_b < 15


def test_plan_fits_space_and_adds_a_quick_companion():
    plan = catalog.plan(["everyday", "code"], ram_gb=32, space_gb=50)
    assert sum(e.size_gb for e in plan) <= 50
    assert len({e.tag for e in plan}) == len(plan)
    assert any(e.speed == "quick" and e.size_gb <= 3.5 for e in plan)


def test_plan_shares_a_model_between_purposes():
    plan = catalog.plan(["everyday", "study"], ram_gb=16, space_gb=30)
    # qwen3.5:9b is top for both at 16 GB, so it is not added twice
    assert [e.tag for e in plan].count("qwen3.5:9b") == 1


def test_rank_prefers_stronger_models():
    assert catalog.rank_of("qwen3.6:35b") > catalog.rank_of("qwen3.5:0.8b")
    assert catalog.rank_of("unknown:7b") == 0
