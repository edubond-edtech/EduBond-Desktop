"""Headless UI smoke test: dashboard -> lesson -> simulated button presses -> results."""
import os

import pytest
from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")


@pytest.fixture
def window(qtbot, tmp_path):
    from edukit.ui.context import AppContext
    from edukit.ui.main_window import MainWindow

    # never touch real USB ports or Bluetooth in tests; use the simulator
    ctx = AppContext(data_dir=tmp_path, hw_overrides={"serial": False, "ble": False, "simulation": True})
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    yield ctx, win
    ctx.shutdown()


def test_full_lesson_in_simulation_mode(window, qtbot):
    ctx, win = window
    assert ctx.devices.device_for("input") and ctx.devices.device_for("output")
    win.home.fb_secs.setValue(0.5)
    win.home.maxq.setValue(3)
    win.home.start()
    assert win.stack.currentWidget() is win.student
    act = win.student.activity
    assert act.current.code == "Q001" and "5 + 3" in win.student.q_text.text()
    assert ctx.sim_input.armed

    ctx.sim_input.press("C")  # correct
    qtbot.waitUntil(lambda: act.state.value == "feedback", timeout=2000)
    assert "Correct" in win.student.banner.text()
    assert ctx.sim_output.history[-1]["color"] == "green"
    qtbot.waitUntil(lambda: act.state.value == "asking" and act.index == 1, timeout=3000)

    ctx.sim_input.press("B")  # wrong (answer A)
    qtbot.waitUntil(lambda: act.state.value == "feedback", timeout=2000)
    assert ctx.sim_output.history[-1]["color"] == "red"
    qtbot.waitUntil(lambda: act.index == 2 and act.state.value == "asking", timeout=3000)

    qtbot.keyClick(win.student, "2")  # keyboard answer "B" (3 x 4 = 12)
    qtbot.waitUntil(lambda: act.state.value == "finished", timeout=4000)
    assert act.score == 2
    assert win.student.pages.currentIndex() == 1

    win.student._exit()
    assert win.stack.currentIndex() == 0  # back on the teacher dashboard (header + tabs)
    assert win.reports.tree.topLevelItemCount() == 6  # one row per student, tests listed under each
    sess = ctx.repo.list_sessions()[0]
    assert sess["correct"] == 2 and sess["answered"] == 3


def test_arabic_mode_switches_to_rtl(window):
    from PySide6.QtCore import Qt

    ctx, win = window
    win.home.start()
    ctx.set_language("ar")
    assert win.student.layoutDirection() == Qt.RightToLeft
    assert "٥" in win.student.q_text.text()
    win.student._exit()


def test_all_tabs_render(window, qtbot):
    ctx, win = window
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        qtbot.wait(20)
    win.devices.refresh()
    assert win.devices.table.rowCount() == 4  # quiz input, quiz LEDs, word-plate board, route map
    win.effects.save()
    assert ctx.repo.get_setting("effect_profile")["correct"]["led"]["effect"] == "wipe"


def test_journey_plates_version_in_simulation(window, qtbot):
    ctx, win = window
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    win.journey.ctype.setCurrentIndex(win.journey.ctype.findData("arrange"))  # word-arrangement competition
    win.journey.bank.setCurrentIndex(win.journey.bank.findText("ترتيب", Qt.MatchContains))
    win.journey.on_wrong.setCurrentIndex(win.journey.on_wrong.findData("retry"))
    win.journey.step_back.setChecked(False)
    win.journey.steps.setValue(2)
    win.journey.fb.setValue(1.0)
    win.journey.shuffle.setChecked(False)
    win.journey.team.setText("فريق النور")
    win.journey.start()
    assert win.stack.currentWidget() is win.journey_view
    act = win.journey_view.activity
    assert act.current.code == "Q101" and ctx.sim_puzzle.armed
    shown = [c.word.text() for c in win.journey_view.plate_cards if not c.isHidden()]
    assert sorted(shown) == sorted("سافر الحجاج من إندونيسيا إلى مكة".split())
    assert shown != "سافر الحجاج من إندونيسيا إلى مكة".split()  # scrambled on the projector
    board = ctx.sim_puzzle
    board.place_all(list(reversed(board.expected)))
    qtbot.waitUntil(lambda: act.state.value == "feedback", timeout=2000)
    assert "غير صحيح" in win.journey_view.banner.text()
    nxt = win.journey_view.next_btn
    assert nxt.isVisibleTo(win.journey_view) and "مرة أخرى" in nxt.text()  # waits for the teacher, no auto-advance
    nxt.click()
    qtbot.waitUntil(lambda: act.state.value == "asking", timeout=1000)
    assert not nxt.isVisibleTo(win.journey_view)
    for _ in range(2):
        board.clear()
        board.place_all(board.expected)
        qtbot.waitUntil(lambda: act.state.value in ("feedback", "arrived"), timeout=2000)
        if act.state.value == "feedback":
            assert "السؤال التالي" in nxt.text()
            nxt.click()
    qtbot.waitUntil(lambda: act.state.value == "arrived", timeout=4000)
    assert ctx.sim_map.history[-1]["command"] == "festival"
    assert "مكة" in win.journey_view.arr_title.text()
    win.journey_view._exit()
    assert ctx.repo.list_sessions()[0]["team_name"] == "فريق النور"


def test_journey_buttons_version_in_simulation(window, qtbot):
    """Default design: one ESP32 = LED map + 4 buttons; Arabic multiple-choice on the projector."""
    ctx, win = window
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    assert "أسئلة الاختيار" in win.journey.bank.currentText()  # Arabic MCQ bank is the default
    win.journey.steps.setValue(2)
    win.journey.fb.setValue(1.0)
    win.journey.shuffle.setChecked(False)
    win.journey.start()
    act = win.journey_view.activity
    m = ctx.sim_map
    assert act.mode_of(act.current) == "buttons" and m.armed and m.question_id == "J001"
    assert win.journey_view.choice_box.isVisible() and not win.journey_view.plates_box.isVisible()
    assert "جاكرتا" in win.journey_view.choice_cards["A"].text.text()
    m.press("A")  # correct
    qtbot.waitUntil(lambda: act.state.value == "feedback", timeout=2000)
    assert act.step == 1 and m.history[-1]["command"] == "path_advance"
    assert "صحيحة" in win.journey_view.banner.text()
    qtbot.waitUntil(lambda: act.state.value == "asking" and act.current.code == "J002", timeout=3000)
    m.press("A")  # wrong (answer B) -> one red step back
    qtbot.waitUntil(lambda: act.state.value == "feedback", timeout=2000)
    assert act.step == 0 and m.history[-1]["command"] == "path_back"
    assert "خاطئة" in win.journey_view.banner.text()
    win.journey_view._exit()


def test_curriculum_students_and_hardware_panels(window):
    ctx, win = window
    win.tabs.setCurrentIndex(win._tab_index(win.curriculum))
    tree = win.curriculum.tree
    names = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert any("المنهج التجريبي" in n for n in names)
    # select the Arabic multiple-choice lesson and see its questions
    it = tree.topLevelItem(names.index(next(n for n in names if "المنهج التجريبي" in n)))
    lesson = it.child(0).child(0).child(0)
    tree.setCurrentItem(lesson)
    assert win.curriculum.table.rowCount() == 10
    assert "›" in win.curriculum.path_lbl.text()
    assert win.students.table.columnCount() == 6 and win.students.table.horizontalHeaderItem(2).text() == "رقم الهوية"
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    assert win.devices.pairing.table.columnCount() == 4  # device search & pair panel exists


def test_question_picture_and_lose_screen(window, qtbot, tmp_path):
    from PIL import Image

    ctx, win = window
    img_dir = ctx.data_dir / "images"
    img_dir.mkdir(exist_ok=True)
    Image.new("RGB", (400, 300), "teal").save(img_dir / "jakarta.png")
    lesson = next(b for b in ctx.repo.list_banks() if "أسئلة الاختيار" in b.name)
    q = ctx.repo.list_questions(lesson.id)[0]
    q.image_path = "jakarta.png"
    ctx.repo.update_question(q)
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    win.journey.reload()
    win.journey.shuffle.setChecked(False)
    win.journey.fb.setValue(0.5)
    win.journey.maxq.setValue(1)
    win.journey.start()
    jv = win.journey_view
    act = jv.activity
    assert act.current.code == "J001"
    qtbot.waitUntil(lambda: jv.q_image.isVisible() and jv.q_image.pixmap() is not None and not jv.q_image.pixmap().isNull(), timeout=2000)
    assert not jv.map.isVisible()  # the on-screen map is gone; the LED strip tracks the journey
    assert "الأسئلة المتبقية" in jv.progress.text()
    ctx.sim_map.press("B")  # wrong -> question limit reached -> lose
    qtbot.waitUntil(lambda: act.state.value == "lost", timeout=3000)
    assert "قبل الوصول" in jv.arr_title.text()
    jv._exit()


def test_whole_interface_in_english(qtbot, tmp_path):
    from edukit.ui.context import AppContext
    from edukit.ui.lang import set_lang
    from edukit.ui.main_window import MainWindow

    set_lang("en")
    try:
        ctx = AppContext(data_dir=tmp_path, hw_overrides={"serial": False, "ble": False, "simulation": True})
        win = MainWindow(ctx)
        qtbot.addWidget(win)
        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        assert any("Journey to Makkah" in t for t in titles) and any("Reports" in t for t in titles)
        assert not any(c for t in titles for c in t if "؀" <= c <= "ۿ")  # no Arabic in the menus
        assert win.layoutDirection() == Qt.LeftToRight
        assert win.devices.type_combo.itemText(0).startswith("Multiple choice")
        assert win.students.table.horizontalHeaderItem(2).text() == "ID number"
        ctx.shutdown()
    finally:
        set_lang("ar")


def test_video_question_and_team_play(window, qtbot):
    ctx, win = window
    from edukit.core.models import Option, Question
    from edukit.ui.journey_view import is_video

    assert is_video("lesson.MP4") and not is_video("photo.png") and not is_video(None)
    (ctx.data_dir / "images").mkdir(exist_ok=True)
    (ctx.data_dir / "images" / "clip.mp4").write_bytes(b"\x00" * 64)  # placeholder file; playback itself needs a real video
    lesson = ctx.repo.ensure_lesson("T", "S", "U", "Video lesson")
    ctx.repo.add_question(Question("V1", {"ar": "شاهد ثم أجب"}, [Option("A", {"ar": "١"}), Option("B", {"ar": "٢"})], ["A"],
                                   bank_id=lesson, image_path="clip.mp4"))
    cid = ctx.repo.list_classes()[0].id
    members = [s.id for s in ctx.repo.list_students(cid)[:3]]
    tid = ctx.repo.add_team(cid, "فريق الأمل", members)
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    win.journey.reload()
    win.journey.bank.setCurrentIndex(win.journey.bank.findData(f"lesson:{lesson}"))
    win.journey.cls.setCurrentIndex(win.journey.cls.findData(cid))
    win.journey.mode.setCurrentIndex(win.journey.mode.findData("team"))
    win.journey.who_combo.setCurrentIndex(win.journey.who_combo.findData(tid))
    assert win.journey.team.text() == "فريق الأمل"
    win.journey.start()
    jv = win.journey_view
    assert jv.media_box.isVisible() and jv.media_box.currentIndex() == 1  # video page shown above the question
    ctx.sim_map.press("A")
    qtbot.waitUntil(lambda: jv.activity.state.value == "feedback", timeout=2000)
    jv._exit()
    sess = ctx.repo.list_sessions()[0]
    assert sess["team_name"] == "فريق الأمل"
    rep = {r["student"].id: r for r in ctx.repo.student_report()}
    assert all(any(s["mode"] == "team" for s in rep[m]["sessions"]) for m in members)  # the test is under each member
    win.reports.refresh()
    assert win.reports.tree.topLevelItemCount() >= 3


def test_excel_media_column_accepts_video(tmp_path):
    import openpyxl

    from edukit.data import excel_io as X
    from edukit.data.repository import Repository

    (tmp_path / "فيديو").mkdir()
    (tmp_path / "فيديو" / "wudu.mp4").write_bytes(b"\x00" * 32)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["النوع", "السؤال", "أ", "ب", "الإجابة الصحيحة", "الصورة أو الفيديو"])
    ws.append(["اختيار", "شاهد الفيديو: ما هذا؟", "وضوء", "صلاة", "أ", "wudu.mp4"])
    ws.append(["اختيار", "ملف غير مدعوم", "١", "٢", "أ", "notes.txt"])
    wb.save(tmp_path / "q.xlsx")
    r = Repository(":memory:")
    lid = r.ensure_lesson("M", "S", "U", "L")
    rep = X.import_questions(r, tmp_path / "q.xlsx", lid, tmp_path / "media")
    assert rep.added == 2 and len(rep.warnings) == 1
    q = r.list_questions(lid)[0]
    assert q.image_path.endswith("wudu.mp4") and (tmp_path / "media" / q.image_path).exists()


def test_media_area_is_always_visible(window):
    ctx, win = window
    win.tabs.setCurrentIndex(win._tab_index(win.journey))
    win.journey.reload()
    win.journey.start()
    jv = win.journey_view
    assert jv.activity.current.image_path in (None, "")  # sample question without media
    assert jv.media_box.isVisible() and jv.media_box.currentIndex() == 2  # placeholder keeps the area in place
    assert "إندونيسيا" in jv.ph_text.text()
    jv._exit()
