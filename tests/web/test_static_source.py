"""INC-19 -- static-source-level checks: no build step, no TypeScript, no
sample/demo data rendered as real, authenticated+CSRF-protected action
calls, no readiness try/finally shortcut. None of these need a real
browser -- plain text inspection of the actual served file, so they run
in the normal (non-egress) suite."""

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[2] / "mcma" / "web"
STATIC_DIR = WEB_DIR / "static"
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")


def test_no_typescript_or_build_step_files_exist():
    assert not any(WEB_DIR.rglob("*.ts"))
    assert not (WEB_DIR / "package.json").exists()
    assert not (WEB_DIR / "tsconfig.json").exists()
    assert not (WEB_DIR / "webpack.config.js").exists()


def test_index_html_lives_outside_the_static_mount():
    """Fable-review-2 correction: index.html must NOT be servable at
    /static/index.html (a second, CSP-header-less copy of the dashboard
    -- a clickjacking surface) -- structurally guaranteed by living
    outside the directory StaticFiles serves, checked here at the
    filesystem level (the HTTP-level 404 is checked in
    tests/app/test_dashboard_mount.py)."""
    assert not (STATIC_DIR / "index.html").exists()


def test_index_references_only_local_static_assets_no_cdn():
    """No build step also means no external script/style dependency --
    everything referenced is served from this same origin."""
    assert "http://" not in INDEX_HTML
    assert "https://" not in INDEX_HTML
    assert 'src="/static/app.js"' in INDEX_HTML


def test_no_inline_script_or_style_in_index_html():
    """CSP is script-src/style-src 'self' with no 'unsafe-inline' -- an
    inline <script> or style="..." attribute would silently violate that
    policy at runtime; checked here so the HTML itself can never
    regress into needing 'unsafe-inline'."""
    assert "<script>" not in INDEX_HTML  # only the external <script src=...> tag is allowed
    assert 'onclick="' not in INDEX_HTML
    assert 'onload="' not in INDEX_HTML


def test_csp_meta_tag_has_no_unsafe_inline_or_unsafe_eval():
    assert "unsafe-inline" not in INDEX_HTML
    assert "unsafe-eval" not in INDEX_HTML


def test_no_sample_data_rendered_as_real():
    """SAMPLE_DATA is structurally null/absent -- there is no hardcoded
    demo notification/job record anywhere in the served JS that could be
    rendered as if it were real claimant data."""
    assert "var SAMPLE_DATA = null" in APP_JS
    # No plausible demo-data literal (a fabricated claim reference, a
    # placeholder claimant name) is embedded in the render/init logic.
    for forbidden in ("DEMO-", "SAMPLE-", "John Doe", "Test Claimant", "EXAMPLE-REF"):
        assert forbidden not in APP_JS


def test_no_finally_block_in_readiness_display():
    """updateReadinessDisplay's try/catch has no `finally` clause that
    could unconditionally set a label after the try/catch runs --
    readiness comes ONLY from the try branch's real check or the catch
    branch's explicit error, never a third, always-executed path. (The
    surrounding comments mention "finally" as documentation of this
    absence -- checked here as actual `finally {` JS syntax, not a bare
    substring match that a comment would also trip.)"""
    start = APP_JS.index("async function updateReadinessDisplay")
    end = APP_JS.index("\n  }\n", start)
    body = APP_JS[start:end]
    assert "finally {" not in body
    assert "finally{" not in body


def test_readiness_never_derives_from_file_existence():
    assert "existsSync" not in APP_JS
    assert "fs.stat" not in APP_JS


def test_all_state_changing_calls_use_credentials_include_and_csrf_header():
    """test_action_updates_require_auth_and_csrf: every POST helper sends
    the session cookie (credentials: 'include') and echoes the CSRF
    cookie back via the X-CSRF-Token header -- structurally, via the one
    shared postAction() helper every action function routes through."""
    start = APP_JS.index("async function postAction")
    end = APP_JS.index("\n  }\n", start)
    body = APP_JS[start:end]
    assert "credentials: \"include\"" in body
    assert "X-CSRF-Token" in body
    assert "readCsrfCookie()" in body

    for action_fn in ("submitJsonDossier", "confirmReviewCompleted", "reportProblem"):
        assert f"postAction(" in APP_JS  # every action goes through the one CSRF-carrying helper
        fn_start = APP_JS.index(f"async function {action_fn}")
        fn_end = APP_JS.index("\n  }\n", fn_start)
        fn_body = APP_JS[fn_start:fn_end]
        assert "postAction(" in fn_body


def test_no_final_action_control_ids_in_markup():
    for forbidden_id in ("enregistrer-btn", "valider-btn", "cloture-btn", "ged-btn"):
        assert f'id="{forbidden_id}"' not in INDEX_HTML


def test_review_completed_and_problem_buttons_exist():
    assert 'id="review-completed-btn"' in INDEX_HTML
    assert 'id="problem-btn"' in INDEX_HTML


def test_account_select_has_no_hardcoded_production_account_id():
    """Pilot-integration correction (section 2/6): no production
    account_id is ever hardcoded in the HTML -- the <select> starts with
    only a placeholder; real options come from populateMcmaAccountSelect()
    (see tests/app/api and the real-Chromium behavior test for its
    MCMA-only filtering)."""
    start = INDEX_HTML.index('id="account-select"')
    end = INDEX_HTML.index("</select>", start)
    select_block = INDEX_HTML[start:end]
    assert "acct-" not in select_block
    assert select_block.count("<option") == 1  # only the placeholder


def test_populate_mcma_account_select_filters_out_mamda_in_source():
    """The MCMA-only filter itself lives in populateMcmaAccountSelect --
    checked here at the source level (a real-DOM proof is a natural
    fit for tests/web/test_escaping.py-style Chromium tests, but the
    filter predicate itself is a plain, directly-inspectable string)."""
    start = APP_JS.index("function populateMcmaAccountSelect")
    end = APP_JS.index("\n  }\n", start)
    body = APP_JS[start:end]
    assert 'a.entity === "MCMA"' in body


def test_manual_review_instructions_are_present():
    assert "Valider" in INDEX_HTML
    assert "Clôture" in INDEX_HTML
    assert "close the browser" in INDEX_HTML.lower()


def test_notifications_and_form_job_are_separate_sections():
    assert 'id="notifications-section"' in INDEX_HTML
    assert 'id="form-job-section"' in INDEX_HTML
    notif_index = INDEX_HTML.index('id="notifications-section"')
    form_index = INDEX_HTML.index('id="form-job-section"')
    assert notif_index != form_index


def test_json_file_input_accepts_only_json():
    assert 'accept=".json,application/json"' in INDEX_HTML
    assert 'type="file"' in INDEX_HTML


def test_dossier_file_reader_rejects_oversized_and_empty_files():
    assert "MAX_DOSSIER_BYTES" in APP_JS
    assert "file too large" in APP_JS
    assert "empty file" in APP_JS


def test_dossier_parser_rejects_non_object_json():
    assert "not a JSON object" in APP_JS


def test_no_dossier_filename_or_path_is_retained_past_the_upload_flow():
    """readDossierFile/parseDossierFileText never store file.name or
    file.path anywhere -- only the parsed JSON object is returned."""
    start = APP_JS.index("function readDossierFile")
    end = APP_JS.index("\n  }\n", start)
    body = APP_JS[start:end]
    assert "file.name" not in body
    assert "file.path" not in body
