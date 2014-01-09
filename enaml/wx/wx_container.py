#------------------------------------------------------------------------------
# Copyright (c) 2013, Nucleic Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#------------------------------------------------------------------------------
from collections import deque

import wx

from atom.api import Atom, Bool, Callable, Float, Typed

from enaml.layout.layout_manager import LayoutItem, LayoutManager
from enaml.widgets.constraints_widget import ConstraintsWidget
from enaml.widgets.container import ProxyContainer

from .wx_constraints_widget import WxConstraintsWidget
from .wx_frame import WxFrame


class LayoutPoint(Atom):
    """ A class which represents a point in layout space.

    """
    #: The x-coordinate of the point.
    x = Float(0.0)

    #: The y-coordinate of the point.
    y = Float(0.0)


class WxLayoutItem(LayoutItem):
    """ A concrete LayoutItem implementation for a WxConstraintsWidget.

    """
    #: The constraints widget declaration object for the layout item.
    declaration = Typed(ConstraintsWidget)

    #: The underlying widget for the layout item.
    widget = Typed(wx.Window)

    #: The layout point which represents the offset of the parent item
    #: from the origin of the root item.
    offset = Typed(LayoutPoint)

    #: The layout point which represents the offset of this item from
    #: the offset of the root item.
    origin = Typed(LayoutPoint)

    def constrainable(self):
        """ Get a reference to the underlying constrainable object.

        Returns
        -------
        result : Contrainable
            An object which implements the Constrainable interface.

        """
        return self.declaration

    def margins(self):
        """ Get the margins for the underlying widget.

        Returns
        -------
        result : tuple
            An empty tuple as constraints widgets do not have margins.

        """
        return ()

    def size_hint(self):
        """ Get the size hint for the underlying widget.

        Returns
        -------
        result : tuple
            A 2-tuple of numbers representing the (width, height)
            size hint of the widget.

        """
        hint = self.widget.GetBestSize()
        return (hint.width, hint.height)

    def constraints(self):
        """ Get the user-defined constraints for the item.

        Returns
        -------
        result : list
            The list of user-defined constraints.

        """
        return self.declaration.layout_constraints()

    def set_geometry(self, x, y, width, height):
        """ Set the geometry of the underlying widget.

        Parameters
        ----------
        x : float
            The new value for the x-origin of the widget.

        y : float
            The new value for the y-origin of the widget.

        width : float
            The new value for the width of the widget.

        height : float
            The new value for the height of the widget.

        """
        origin = self.origin
        origin.x = x
        origin.y = y
        offset = self.offset
        x -= offset.x
        y -= offset.y
        self.widget.SetDimensions(x, y, width, height)


class WxContainerItem(WxLayoutItem):
    """ A WxLayoutItem subclass which handles container margins.

    """
    #: A callable used to get the container widget margins.
    margins_func = Callable()

    def margins(self):
        """ Get the margins for the underlying widget.

        Returns
        -------
        result : tuple
            A 4-tuple of ints representing the container margins.

        """
        a, b, c, d = self.declaration.padding
        e, f, g, h = self.margins_func(self.widget)
        return (a + e, b + f, c + g, d + h)


class WxSharedContainerItem(WxContainerItem):
    """ A WxContainerItem subclass which works for shared containers.

    """
    def size_hint_constraints(self):
        """ Get the size hint constraints for the item.

        A shared container does not generate size hint constraints.

        """
        return []


class WxChildContainerItem(WxLayoutItem):
    """ A WxLayoutItem subclass which works for child containers.

    """
    def constraints(self):
        """ Get the user constraints for the item.

        A child container does not expose its user layout constraints.

        """
        return []


class wxContainer(wx.PyPanel):
    """ A subclass of wx.PyPanel which allows the default best size to
    be overriden by calling SetBestSize.

    This functionality is used by the WxContainer to override the
    size hint with a value computed from the constraints layout
    manager.

    """
    #: An invalid wx.Size used as the default value for class instances.
    _best_size = wx.Size(-1, -1)

    def DoGetBestSize(self):
        """ Reimplemented parent class method.

        This will return the best size as set by a call to SetBestSize.
        If that is invalid, then the superclass' version will be used.

        """
        size = self._best_size
        if not size.IsFullySpecified():
            size = super(wxContainer, self).DoGetBestSize()
        return size

    def SetBestSize(self, size):
        """ Sets the best size to use for this container.

        """
        self._best_size = size


class wxLayoutTimer(wx.Timer):
    """ A custom wx Timer which for collapsing layout requests.

    """
    def __init__(self, owner):
        super(wxLayoutTimer, self).__init__()
        self.owner = owner

    def Notify(self):
        self.owner._on_relayout_timer()


class WxContainer(WxFrame, ProxyContainer):
    """ A Wx implementation of an Enaml ProxyContainer.

    """
    #: A reference to the toolkit widget created by the proxy.
    widget = Typed(wxContainer)

    #: A timer used to collapse relayout requests. The timer is created
    #: on an as needed basis and destroyed when it is no longer needed.
    _layout_timer = Typed(wxLayoutTimer)

    #: The layout manager which handles the system of constraints.
    _layout_manager = Typed(LayoutManager)

    #: Whether or not the current container is shown. This is toggled
    #: by the EVT_SHOW handler.
    _is_shown = Bool(True)

    def destroy(self):
        """ A reimplemented destructor.

        This destructor clears the layout timer and layout manager
        so that any potential reference cycles are broken.

        """
        timer = self._layout_timer
        if timer is not None:
            timer.Stop()
            del self._layout_timer
        del self._layout_manager
        super(WxContainer, self).destroy()

    #--------------------------------------------------------------------------
    # Initialization API
    #--------------------------------------------------------------------------
    def create_widget(self):
        """ Creates the QContainer widget.

        """
        self.widget = wxContainer(self.parent_widget())

    def init_layout(self):
        """ Initialize the layout of the widget.

        """
        super(WxContainer, self).init_layout()
        self._setup_manager()
        self._update_sizes()
        self._update_geometries()
        widget = self.widget
        widget.Bind(wx.EVT_SIZE, self._on_resized)
        widget.Bind(wx.EVT_SHOW, self._on_shown)

    #--------------------------------------------------------------------------
    # Layout API
    #--------------------------------------------------------------------------
    def request_relayout(self):
        """ Request a relayout of the container.

        """
        # If this container owns the layout, (re)start the timer. The
        # list of layout items is reset to prevent an edge case where
        # a parent container layout occurs before the child container,
        # causing the child to resize potentially deleted widgets which
        # still have strong refs in the layout items list.
        manager = self._layout_manager
        if manager is not None:
            if self._layout_timer is None:
                manager.set_items([])
                self.widget.Freeze()
                self._layout_timer = wxLayoutTimer(self)
            self._layout_timer.Start(1, oneShot=True)
            return

        # If an ancestor container owns the layout, proxy the call.
        container = self.layout_container
        if container is not None:
            container.request_relayout()

    def size_hint_updated(self, item=None):
        """ Notify the layout system that the size hint has changed.

        Parameters
        ----------
        item : WxConstraintsWidget, optional
            The constraints widget with the updated size hint. If this
            is None, it indicates that this container's size hint is
            the one which has changed.

        """
        # If this container's size hint has changed and it has an
        # ancestor layout container, notify that container since it
        # cares about this container's size hint. If the layout for
        # this container is shared, the layout item will take care
        # of supplying the empty list size hint constraints.
        container = self.layout_container
        if item is None:
            if container is not None:
                container.size_hint_updated(self)
            self.update_geometry()
            return

        # If this container owns its layout, update the manager unless
        # a relayout is pending. A pending relayout means the manager
        # has already been reset and the layout indices are invalid.
        manager = self._layout_manager
        if manager is not None:
            if self._layout_timer is None:
                with self.size_hint_guard():
                    manager.update_size_hint(item.layout_index)
                    self._update_sizes()
                    self._update_geometries()
            return

        # If an ancestor container owns the layout, proxy the call.
        if container is not None:
            container.size_hint_updated(item)

    @staticmethod
    def margins_func(widget_item):
        """ Get the margins for the given widget item.

        The container margins are added to the user provided padding
        to determine the final offset from a layout box boundary to
        the corresponding content line. The default container margins
        are zero. This method can be reimplemented by subclasses to
        supply different margins.

        Returns
        -------
        result : tuple
            A 4-tuple of margins (top, right, bottom, left).

        """
        return (0, 0, 0, 0)

    def margins_updated(self, item=None):
        """ Notify the layout system that the margins have changed.

        Parameters
        ----------
        item : WxContainer, optional
            The container widget with the updated margins. If this is
            None, it indicates that this container's margins are the
            ones which have changed.

        """
        # If this container owns its layout, update the manager unless
        # a relayout is pending. A pending relayout means the manager
        # has already been reset and the layout indices are invalid.
        manager = self._layout_manager
        if manager is not None:
            if self._layout_timer is None:
                index = item.layout_index if item else -1
                with self.size_hint_guard():
                    manager.update_margins(index)
                    self._update_sizes()
                    self._update_geometries()
            return

        # If an ancestor container owns the layout, forward the call.
        container = self.layout_container
        if container is not None:
            container.margins_updated(item or self)

    #--------------------------------------------------------------------------
    # Private Event Handlers
    #--------------------------------------------------------------------------
    def _on_resized(self, event):
        """ The event handler for the EVT_SIZE event.

        This triggers a geometry update for the decendant children.

        """
        if self._is_shown:
            self._update_geometries()

    def _on_shown(self, event):
        """ The event handler for the EVT_SHOW event.

        This handler toggles the value of the _is_shown flag.

        """
        # The EVT_SHOW event is not reliable. For example, it is not
        # emitted on the children of widgets that were hidden. So, if
        # this container is the child of, say, a notebook page, then
        # the switching of tabs does not emit a show event. So, the
        # notebook page must cooperatively emit a show event on this
        # container. Therefore, we can't treat this event as a 'real'
        # toolkit event, we just use it as a hint.
        self._is_shown = shown = event.GetShow()
        if shown:
            self._update_geometries()

    def _on_relayout_timer(self):
        """ Rebuild the layout for the container.

        This method is invoked when the relayout timer is triggered. It
        will reset the manager and update the geometries of the children.

        """
        del self._layout_timer
        with self.size_hint_guard():
            self._setup_manager()
            self._update_sizes()
            self._update_geometries()
        self.widget.Thaw()

    #--------------------------------------------------------------------------
    # Private Layout Handling
    #--------------------------------------------------------------------------
    def _setup_manager(self):
        """ Setup the layout manager.

        This method will create or reset the layout manager and update
        it with a new layout table.

        """
        # Layout ownership can only be transferred *after* the init
        # layout method is called, as layout occurs bottom up. The
        # manager is only created if ownership is unlikely to change.
        share_layout = self.declaration.share_layout
        if share_layout and isinstance(self.parent(), WxContainer):
            timer = self._layout_timer
            if timer is not None:
                timer.Stop()
            del self._layout_timer
            del self._layout_manager
            return

        manager = self._layout_manager
        if manager is None:
            item = WxContainerItem()
            item.declaration = self.declaration
            item.widget = self.widget
            item.origin = LayoutPoint()
            item.offset = LayoutPoint()
            item.margins_func = self.margins_func
            manager = self._layout_manager = LayoutManager(item)
        manager.set_items(self._create_layout_items())

    def _update_geometries(self):
        """ Update the geometries of the layout children.

        This method will resize the layout manager to the container size.

        """
        manager = self._layout_manager
        if manager is not None:
            width, height = self.widget.GetSizeTuple()
            manager.resize(width, height)

    def _update_sizes(self):
        """ Update the sizes of the underlying container.

        This method will update the min, max, and best size of the
        container. It will not automatically trigger a size hint
        notification.

        """
        widget = self.widget
        manager = self._layout_manager
        if manager is None:
            widget.SetBestSize(wx.Size(-1, -1))
            widget.SetMinSize(wx.Size(0, 0))
            widget.SetMaxSize(wx.Size(16777215, 16777215))
            return

        widget.SetBestSize(wx.Size(*manager.best_size()))
        if not isinstance(widget.GetParent(), wxContainer):
            # Only set min and max size if the parent is not a container.
            # The manager needs to be the ultimate authority when dealing
            # with nested containers, since QWidgetItem respects min and
            # max size when calling setGeometry().
            widget.SetMinSize(wx.Size(*manager.min_size()))
            widget.SetMaxSize(wx.Size(*manager.max_size()))

    def _create_layout_items(self):
        """ Create a layout items for the container decendants.

        The layout items are created by traversing the decendants in
        breadth-first order and setting up a LayoutItem object for
        each decendant. The layout item is populated with an offset
        point which represents the offset of the widgets parent to
        the origin of the widget which owns the layout solver. This
        point is substracted from the solved origin of the widget.

        Returns
        -------
        result : list
            A list of LayoutItem objects which represent the flat
            layout traversal.

        """
        layout_items = []
        offset = LayoutPoint()
        queue = deque((offset, child) for child in self.children())
        while queue:
            offset, child = queue.popleft()
            if isinstance(child, WxConstraintsWidget):
                child.layout_container = self
                origin = LayoutPoint()
                if isinstance(child, WxContainer):
                    if child.declaration.share_layout:
                        item = WxSharedContainerItem()
                        item.margins_func = child.margins_func
                        for subchild in child.children():
                            queue.append((origin, subchild))
                    else:
                        item = WxChildContainerItem()
                else:
                    item = WxLayoutItem()
                item.declaration = child.declaration
                item.widget = child.widget
                item.offset = offset
                item.origin = origin
                child.layout_index = len(layout_items)
                layout_items.append(item)
        return layout_items
