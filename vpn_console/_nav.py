"""Shared navigation mixin for wizard screens: escape goes back."""

from textual.screen import Screen


class BackMixin(Screen):
    def action_back(self):
        if self.app.screen_stack:
            self.app.pop_screen()
