from app.modules.chat_bot import answer_utils as au


def test_strip_markdown_removes_headers_and_backticks_but_keeps_bold_and_bullets():
    text = "## Title\nThe `location_count` is **high**.\n- one\n- two"
    assert au.strip_markdown_formatting(text) == "Title\nThe location_count is **high**.\n- one\n- two"
    assert au.strip_markdown_formatting("") == ""


def test_display_value_formats_iso_timestamps_only():
    assert au.display_value("2026-10-07T21:45:38.599000+00:00") == "2026-10-07 21:45:38 UTC"
    assert au.display_value("2026-10-07T21:45:38Z") == "2026-10-07 21:45:38 UTC"
    assert au.display_value("2026-10-07T17:45:38-04:00") == "2026-10-07 21:45:38 UTC"
    assert au.display_value("2026-10-07") == "2026-10-07"
    assert au.display_value("7876782117") == "7876782117"
    assert au.display_value(5) == 5
    assert au.display_value(None) is None


def test_infer_fields_reads_the_values_and_never_parses_strings_as_numbers():
    rows = [
        {"week": "2026-09-28", "visits": 12, "rate": 0.5, "flag": True, "phone": "7876782117", "at": "2026-10-07 21:45:38 UTC", "empty": None},
        {"week": "2026-10-05", "visits": 9, "rate": 1.5, "flag": False, "phone": "7870000000", "at": "2026-10-08 01:00:00 UTC", "empty": None},
    ]
    types = {f["name"]: f["type"] for f in au.infer_fields(list(rows[0]), rows)}
    assert types == {
        "week": "DATE", "visits": "FLOAT64", "rate": "FLOAT64", "flag": "BOOL",
        "phone": "STRING", "at": "TIMESTAMP", "empty": "STRING",
    }


def test_infer_charts_line_for_dates_bar_for_categories_none_for_a_single_row():
    weeks = [{"week": "2026-09-28", "visits": 12}, {"week": "2026-10-05", "visits": 9}]
    chart = au.infer_charts(au.infer_fields(["week", "visits"], weeks), weeks)[0]
    assert (chart["type"], chart["x_field"], chart["y_field"]) == ("line", "week", "visits")

    tiers = [{"tier": "Basic", "n": 3}, {"tier": "Premium", "n": 5}]
    assert au.infer_charts(au.infer_fields(["tier", "n"], tiers), tiers)[0]["type"] == "bar"

    one = [{"active": 11410}]
    assert au.infer_charts(au.infer_fields(["active"], one), one) == []
    names = [{"full_name": "A", "email": "a@x"}, {"full_name": "B", "email": "b@x"}]
    assert au.infer_charts(au.infer_fields(["full_name", "email"], names), names) == []


def test_partial_list_note_wording():
    exact = au.build_partial_list_note(500, 8412, True, 5230)
    assert exact.startswith("Note: the table shows the first 500 of 8,412 matching rows (5,230 unique customers).")
    assert "more than 3,000" in au.build_partial_list_note(500, 3000, False, None)


def test_fixed_notes_are_stable_text():
    assert au.CUSTOMER_LEVEL_ACTIVE_NOTE.startswith("Note: this figure is at the customer level.")
    assert "backup engine" in au.BACKUP_ENGINE_NOTE
