"""Preview source locations recorded during ReportLab layout, not text guesses."""
from copy import deepcopy
from reportlab.platypus import Paragraph


class SourceParagraph(Paragraph):
    def __init__(self, *args, source=None, regions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source, self.regions = source, regions

    def __deepcopy__(self, memo):
        # BalancedColumns measures copies of paragraphs. The measurements may
        # draw the final fragments, so all copies must report to one source map.
        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for name, value in self.__dict__.items():
            setattr(clone, name, value if name == 'regions' else deepcopy(value, memo))
        return clone

    def split(self, availWidth, availHeight):
        fragments = super().split(availWidth, availHeight)
        for i, fragment in enumerate(fragments):
            # ReportLab returns base Paragraph objects here. Keep our draw hook
            # on every fragment so click-to-edit survives page/column breaks.
            fragment.__class__ = self.__class__
            fragment.source, fragment.regions = self.source, self.regions
            if hasattr(self,'rule_color'):
                fragment.rule_color = self.rule_color if i==len(fragments)-1 else None
            if hasattr(self,'timeline_dot'):
                fragment.timeline_dot = self.timeline_dot if i==0 else False
        return fragments

    def draw(self):
        if self.source is not None and self.regions is not None:
            x, y = self.canv.absolutePosition(0, 0)
            height = self.canv._pagesize[1]
            self.regions.append(dict(page=self.canv.getPageNumber()-1,
                                     rect=(x, height-y-self.height, x+self.width, height-y),
                                     source=self.source))
        super().draw()
