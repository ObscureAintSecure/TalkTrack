# tests/test_edit_history.py
import unittest


class TestEditHistory(unittest.TestCase):
    def test_initial_state(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        self.assertEqual(h.current(), "original")
        self.assertFalse(h.can_undo())
        self.assertFalse(h.can_redo())

    def test_push_and_undo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        self.assertEqual(h.current(), "edit1")
        self.assertTrue(h.can_undo())
        result = h.undo()
        self.assertEqual(result, "original")
        self.assertFalse(h.can_undo())

    def test_undo_then_redo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        h.undo()
        self.assertTrue(h.can_redo())
        result = h.redo()
        self.assertEqual(result, "edit2")

    def test_push_clears_redo(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        h.undo()
        h.push("edit3")
        self.assertFalse(h.can_redo())
        self.assertEqual(h.current(), "edit3")

    def test_max_depth(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original", max_depth=5)
        for i in range(10):
            h.push(f"edit{i}")
        self.assertEqual(h.current(), "edit9")
        count = 0
        while h.can_undo():
            h.undo()
            count += 1
        self.assertEqual(count, 5)

    def test_is_modified(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        self.assertFalse(h.is_modified())
        h.push("edit1")
        self.assertTrue(h.is_modified())
        h.undo()
        self.assertFalse(h.is_modified())

    def test_original_text(self):
        from app.ui.segment_widget import EditHistory
        h = EditHistory("original")
        h.push("edit1")
        h.push("edit2")
        self.assertEqual(h.original(), "original")


if __name__ == "__main__":
    unittest.main()
