#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ROLE_PROPERTY "_WTWM_CANONICAL_ROLE"
#define READY_PROPERTY "_WTWM_CANONICAL_READY"
#define FIXTURE_CLASS "WtwmCanonical"
#define LEGACY_NAME "wtwm-legacy-xterm"
#define LEGACY_CLASS "WtwmLegacyXterm"
#define ICON_SIZE 16U
#define FIXTURE_ROLE_COUNT 8U

static const char initial_long_title[] =
    "WTWM canonical long title 001 | abcdefghijklmnopqrstuvwxyz | "
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ | 0123456789 | "
    "the complete title must survive an X11 property round trip before "
    "mutation | abcdefghijklmnopqrstuvwxyz | ABCDEFGHIJKLMNOPQRSTUVWXYZ | "
    "0123456789 | end";
static const char mutated_title[] =
    "WTWM canonical title mutation observed: revision 2";

static const char *const fixture_roles[FIXTURE_ROLE_COUNT] = {
    "normal",
    "dialog",
    "fixed",
    "resize",
    "title",
    "icon",
    "urgent",
    "override",
};

static _Noreturn void
die(const char *message)
{
    fprintf(stderr, "canonical X11 client: %s\n", message);
    exit(EXIT_FAILURE);
}

static void
pause_milliseconds(long milliseconds)
{
    struct timespec duration;

    duration.tv_sec = milliseconds / 1000;
    duration.tv_nsec = (milliseconds % 1000) * 1000000L;
    while (nanosleep(&duration, &duration) != 0 && errno == EINTR) {
    }
}

static void
pass(const char *assertion)
{
    printf("PASS\t%s\n", assertion);
}

static void
expect(int condition, const char *message)
{
    if (!condition) {
        die(message);
    }
}

static void
set_role(Display *display, Window window, const char *role)
{
    Atom role_atom = XInternAtom(display, ROLE_PROPERTY, False);

    XChangeProperty(display, window, role_atom, XA_STRING, 8, PropModeReplace,
                    (const unsigned char *) role, (int) strlen(role));
}

static int
read_role(Display *display, Window window, char *buffer, size_t buffer_size)
{
    Atom role_atom = XInternAtom(display, ROLE_PROPERTY, False);
    Atom actual_type;
    int actual_format;
    unsigned long item_count;
    unsigned long bytes_after;
    unsigned char *data = NULL;
    int found = 0;

    if (XGetWindowProperty(display, window, role_atom, 0, 64, False, XA_STRING,
                           &actual_type, &actual_format, &item_count,
                           &bytes_after, &data) == Success &&
        actual_type == XA_STRING && actual_format == 8 && item_count > 0 &&
        item_count < buffer_size) {
        memcpy(buffer, data, item_count);
        buffer[item_count] = '\0';
        found = 1;
    }
    if (data != NULL) {
        XFree(data);
    }
    return found;
}

static int
find_role_recursive(Display *display, Window window, const char *wanted,
                    unsigned int depth, Window *result)
{
    Window root;
    Window parent;
    Window *children = NULL;
    unsigned int child_count = 0;
    char role[64];
    unsigned int i;

    if (read_role(display, window, role, sizeof(role)) &&
        strcmp(role, wanted) == 0) {
        *result = window;
        return 1;
    }
    if (depth == 0 ||
        !XQueryTree(display, window, &root, &parent, &children, &child_count)) {
        return 0;
    }
    for (i = 0; i < child_count; i++) {
        if (find_role_recursive(display, children[i], wanted, depth - 1,
                                result)) {
            XFree(children);
            return 1;
        }
    }
    if (children != NULL) {
        XFree(children);
    }
    return 0;
}

static Window
find_role(Display *display, const char *role)
{
    Window result = None;

    if (!find_role_recursive(display, DefaultRootWindow(display), role, 8,
                             &result)) {
        die("could not find a canonical role");
    }
    return result;
}

static int
window_has_class(Display *display, Window window, const char *name,
                 const char *class_name)
{
    XClassHint class_hint;
    int matches = 0;

    class_hint.res_name = NULL;
    class_hint.res_class = NULL;
    if (XGetClassHint(display, window, &class_hint)) {
        matches = class_hint.res_name != NULL && class_hint.res_class != NULL &&
                  strcmp(class_hint.res_name, name) == 0 &&
                  strcmp(class_hint.res_class, class_name) == 0;
    }
    if (class_hint.res_name != NULL) {
        XFree(class_hint.res_name);
    }
    if (class_hint.res_class != NULL) {
        XFree(class_hint.res_class);
    }
    return matches;
}

static int
find_class_recursive(Display *display, Window window, const char *name,
                     const char *class_name, unsigned int depth,
                     Window *result)
{
    Window root;
    Window parent;
    Window *children = NULL;
    unsigned int child_count = 0;
    unsigned int i;

    if (window_has_class(display, window, name, class_name)) {
        *result = window;
        return 1;
    }
    if (depth == 0 ||
        !XQueryTree(display, window, &root, &parent, &children, &child_count)) {
        return 0;
    }
    for (i = 0; i < child_count; i++) {
        if (find_class_recursive(display, children[i], name, class_name,
                                 depth - 1, result)) {
            XFree(children);
            return 1;
        }
    }
    if (children != NULL) {
        XFree(children);
    }
    return 0;
}

static int
query_parent(Display *display, Window window, Window *parent)
{
    Window root;
    Window *children = NULL;
    unsigned int child_count = 0;
    int status;

    status = XQueryTree(display, window, &root, parent, &children,
                        &child_count);
    if (children != NULL) {
        XFree(children);
    }
    return status;
}

static int
is_managed(Display *display, Window client)
{
    Window root = DefaultRootWindow(display);
    Window parent = None;

    return query_parent(display, client, &parent) && parent != None &&
           parent != root && parent != client;
}

static unsigned long
named_pixel(Display *display, const char *name)
{
    int screen = DefaultScreen(display);
    XColor exact;
    XColor screen_color;

    if (!XAllocNamedColor(display, DefaultColormap(display, screen), name,
                          &screen_color, &exact)) {
        die("could not allocate a fixture color");
    }
    return screen_color.pixel;
}

static Window
create_fixture_window(Display *display, const char *role, const char *title,
                      int x, int y, unsigned int width, unsigned int height,
                      int override_redirect)
{
    Window root = DefaultRootWindow(display);
    XSetWindowAttributes attributes;
    unsigned long mask = CWBackPixel;
    Window window;
    XClassHint class_hint;
    XSizeHints size_hints;
    XWMHints wm_hints;

    attributes.background_pixel = named_pixel(display, "#405060");
    attributes.override_redirect = override_redirect;
    if (override_redirect) {
        mask |= CWOverrideRedirect;
    }
    window = XCreateWindow(display, root, x, y, width, height, 0,
                           CopyFromParent, InputOutput, CopyFromParent, mask,
                           &attributes);
    set_role(display, window, role);
    XStoreName(display, window, title);
    XSetIconName(display, window, role);

    class_hint.res_name = (char *) role;
    class_hint.res_class = (char *) FIXTURE_CLASS;
    XSetClassHint(display, window, &class_hint);

    memset(&size_hints, 0, sizeof(size_hints));
    size_hints.flags = USPosition | USSize;
    size_hints.x = x;
    size_hints.y = y;
    size_hints.width = (int) width;
    size_hints.height = (int) height;
    XSetWMNormalHints(display, window, &size_hints);

    memset(&wm_hints, 0, sizeof(wm_hints));
    wm_hints.flags = InputHint;
    wm_hints.input = True;
    XSetWMHints(display, window, &wm_hints);
    XSelectInput(display, window, ExposureMask | StructureNotifyMask);
    return window;
}

static Pixmap
create_depth_one_pixmap(Display *display, Window root, int inverse)
{
    Pixmap pixmap = XCreatePixmap(display, root, ICON_SIZE, ICON_SIZE, 1);
    XGCValues values;
    GC gc;

    values.foreground = inverse ? 1UL : 0UL;
    values.background = inverse ? 0UL : 1UL;
    gc = XCreateGC(display, pixmap, GCForeground | GCBackground, &values);
    XFillRectangle(display, pixmap, gc, 0, 0, ICON_SIZE, ICON_SIZE);
    XSetForeground(display, gc, inverse ? 0UL : 1UL);
    XFillRectangle(display, pixmap, gc, 3, 3, 10, 10);
    XFreeGC(display, gc);
    return pixmap;
}

static void
run_server(Display *display)
{
    Window root = DefaultRootWindow(display);
    Window windows[FIXTURE_ROLE_COUNT];
    XSizeHints size_hints;
    XWMHints wm_hints;
    Atom net_wm_window_type;
    Atom net_wm_window_type_dialog;
    Atom ready_atom;
    unsigned long ready = 1;
    Pixmap icon_pixmap;
    Pixmap icon_mask;
    unsigned int i;

    windows[0] = create_fixture_window(display, "normal", "Canonical Normal",
                                       30, 30, 200, 100, 0);
    windows[1] = create_fixture_window(display, "dialog", "Canonical Dialog",
                                       80, 90, 180, 80, 0);
    XSetTransientForHint(display, windows[1], windows[0]);
    net_wm_window_type = XInternAtom(display, "_NET_WM_WINDOW_TYPE", False);
    net_wm_window_type_dialog =
        XInternAtom(display, "_NET_WM_WINDOW_TYPE_DIALOG", False);
    XChangeProperty(display, windows[1], net_wm_window_type, XA_ATOM, 32,
                    PropModeReplace,
                    (const unsigned char *) &net_wm_window_type_dialog, 1);

    windows[2] = create_fixture_window(display, "fixed", "Canonical Fixed",
                                       300, 30, 140, 90, 0);
    memset(&size_hints, 0, sizeof(size_hints));
    size_hints.flags = USPosition | USSize | PMinSize | PMaxSize;
    size_hints.x = 300;
    size_hints.y = 30;
    size_hints.width = 140;
    size_hints.height = 90;
    size_hints.min_width = 140;
    size_hints.min_height = 90;
    size_hints.max_width = 140;
    size_hints.max_height = 90;
    XSetWMNormalHints(display, windows[2], &size_hints);

    windows[3] = create_fixture_window(display, "resize", "Canonical Resize",
                                       470, 30, 210, 130, 0);
    memset(&size_hints, 0, sizeof(size_hints));
    size_hints.flags = USPosition | USSize | PBaseSize | PResizeInc | PAspect;
    size_hints.x = 470;
    size_hints.y = 30;
    size_hints.width = 210;
    size_hints.height = 130;
    size_hints.base_width = 40;
    size_hints.base_height = 30;
    size_hints.width_inc = 13;
    size_hints.height_inc = 7;
    size_hints.min_aspect.x = 4;
    size_hints.min_aspect.y = 3;
    size_hints.max_aspect.x = 16;
    size_hints.max_aspect.y = 9;
    XSetWMNormalHints(display, windows[3], &size_hints);

    windows[4] = create_fixture_window(display, "title", initial_long_title,
                                       30, 260, 400, 100, 0);

    windows[5] = create_fixture_window(display, "icon", "Canonical Icon",
                                       450, 260, 160, 100, 0);
    XSetIconName(display, windows[5], "WTWM canonical icon name");
    icon_pixmap = create_depth_one_pixmap(display, root, 0);
    icon_mask = create_depth_one_pixmap(display, root, 1);
    memset(&wm_hints, 0, sizeof(wm_hints));
    wm_hints.flags = InputHint | IconPixmapHint | IconMaskHint;
    wm_hints.input = True;
    wm_hints.icon_pixmap = icon_pixmap;
    wm_hints.icon_mask = icon_mask;
    XSetWMHints(display, windows[5], &wm_hints);

    windows[6] = create_fixture_window(display, "urgent", "Canonical Urgent",
                                       640, 260, 160, 100, 0);
    memset(&wm_hints, 0, sizeof(wm_hints));
    wm_hints.flags = InputHint | XUrgencyHint;
    wm_hints.input = True;
    XSetWMHints(display, windows[6], &wm_hints);

    windows[7] = create_fixture_window(display, "override",
                                       "Canonical Override Redirect", 780, 30,
                                       160, 70, 1);

    for (i = 0; i < FIXTURE_ROLE_COUNT; i++) {
        XMapWindow(display, windows[i]);
        XSync(display, False);
        pause_milliseconds(25);
    }
    ready_atom = XInternAtom(display, READY_PROPERTY, False);
    XChangeProperty(display, root, ready_atom, XA_CARDINAL, 32,
                    PropModeReplace, (const unsigned char *) &ready, 1);
    XSync(display, False);

    for (;;) {
        XEvent event;

        XNextEvent(display, &event);
        if (event.type == Expose) {
            XClearWindow(display, event.xexpose.window);
        }
    }
}

static int
fixtures_ready(Display *display)
{
    Window root = DefaultRootWindow(display);
    Atom ready_atom = XInternAtom(display, READY_PROPERTY, False);
    Atom actual_type;
    int actual_format;
    unsigned long item_count;
    unsigned long bytes_after;
    unsigned char *data = NULL;
    unsigned int i;
    int ready = 0;

    if (XGetWindowProperty(display, root, ready_atom, 0, 1, False, XA_CARDINAL,
                           &actual_type, &actual_format, &item_count,
                           &bytes_after, &data) == Success &&
        actual_type == XA_CARDINAL && actual_format == 32 && item_count == 1 &&
        data != NULL && *(const unsigned long *) data == 1UL) {
        ready = 1;
    }
    if (data != NULL) {
        XFree(data);
    }
    if (!ready) {
        return 0;
    }
    for (i = 0; i < FIXTURE_ROLE_COUNT; i++) {
        Window window = None;

        if (!find_role_recursive(display, root, fixture_roles[i], 8, &window)) {
            return 0;
        }
        if (strcmp(fixture_roles[i], "override") == 0) {
            Window parent = None;
            XWindowAttributes attributes;

            if (!query_parent(display, window, &parent) || parent != root ||
                !XGetWindowAttributes(display, window, &attributes) ||
                !attributes.override_redirect) {
                return 0;
            }
        } else if (!is_managed(display, window)) {
            return 0;
        }
    }
    return 1;
}

static void
wait_for_fixtures(Display *display)
{
    int attempt;

    for (attempt = 0; attempt < 200; attempt++) {
        if (fixtures_ready(display)) {
            return;
        }
        pause_milliseconds(25);
    }
    die("fixtures did not become ready and managed");
}

static void
tag_legacy_xterm(Display *display)
{
    Window window = None;
    int attempt;

    for (attempt = 0; attempt < 200; attempt++) {
        if (find_class_recursive(display, DefaultRootWindow(display),
                                 LEGACY_NAME, LEGACY_CLASS, 8, &window) &&
            is_managed(display, window)) {
            set_role(display, window, "legacy-xterm");
            XSync(display, False);
            return;
        }
        pause_milliseconds(25);
    }
    die("legacy xterm did not appear with the expected class and frame");
}

static int
has_atom_property(Display *display, Window window, Atom property,
                  Atom wanted)
{
    Atom actual_type;
    int actual_format;
    unsigned long item_count;
    unsigned long bytes_after;
    unsigned char *data = NULL;
    int matches = 0;

    if (XGetWindowProperty(display, window, property, 0, 8, False, XA_ATOM,
                           &actual_type, &actual_format, &item_count,
                           &bytes_after, &data) == Success &&
        actual_type == XA_ATOM && actual_format == 32 && item_count == 1 &&
        data != NULL && *(const Atom *) data == wanted) {
        matches = 1;
    }
    if (data != NULL) {
        XFree(data);
    }
    return matches;
}

static int
pixmap_has_geometry(Display *display, Pixmap pixmap, unsigned int wanted_width,
                    unsigned int wanted_height, unsigned int wanted_depth)
{
    Window root;
    int x;
    int y;
    unsigned int width;
    unsigned int height;
    unsigned int border_width;
    unsigned int depth;

    return pixmap != None &&
           XGetGeometry(display, pixmap, &root, &x, &y, &width, &height,
                        &border_width, &depth) &&
           width == wanted_width && height == wanted_height &&
           depth == wanted_depth;
}

static void
verify_managed(Display *display, const char *role, const char *assertion)
{
    expect(is_managed(display, find_role(display, role)),
           "expected role is not managed by reference twm");
    pass(assertion);
}

static void
verify_initial(Display *display)
{
    Window normal = find_role(display, "normal");
    Window dialog = find_role(display, "dialog");
    Window fixed = find_role(display, "fixed");
    Window resize = find_role(display, "resize");
    Window title = find_role(display, "title");
    Window icon = find_role(display, "icon");
    Window urgent = find_role(display, "urgent");
    Window override = find_role(display, "override");
    Window legacy = find_role(display, "legacy-xterm");
    Window root = DefaultRootWindow(display);
    Window transient_for = None;
    Window parent = None;
    XSizeHints size_hints;
    long supplied_hints = 0;
    XWMHints *wm_hints;
    XWindowAttributes attributes;
    char *name = NULL;
    char *icon_name = NULL;
    Atom net_wm_window_type =
        XInternAtom(display, "_NET_WM_WINDOW_TYPE", False);
    Atom net_wm_window_type_dialog =
        XInternAtom(display, "_NET_WM_WINDOW_TYPE_DIALOG", False);

    verify_managed(display, "normal", "normal-managed");
    expect(!XGetTransientForHint(display, normal, &transient_for),
           "normal fixture unexpectedly has WM_TRANSIENT_FOR");
    pass("normal-no-transient");

    verify_managed(display, "dialog", "dialog-managed");
    expect(XGetTransientForHint(display, dialog, &transient_for) &&
               transient_for == normal,
           "dialog WM_TRANSIENT_FOR does not name the normal fixture");
    pass("dialog-transient-for-normal");
    expect(has_atom_property(display, dialog, net_wm_window_type,
                             net_wm_window_type_dialog),
           "dialog is missing _NET_WM_WINDOW_TYPE_DIALOG");
    pass("dialog-window-type");

    verify_managed(display, "fixed", "fixed-managed");
    expect(XGetWMNormalHints(display, fixed, &size_hints, &supplied_hints) &&
               (size_hints.flags & (PMinSize | PMaxSize)) ==
                   (PMinSize | PMaxSize) &&
               size_hints.min_width == 140 && size_hints.min_height == 90 &&
               size_hints.max_width == 140 && size_hints.max_height == 90,
           "fixed fixture does not expose exact min=max size hints");
    pass("fixed-min-max");

    verify_managed(display, "resize", "resize-managed");
    supplied_hints = 0;
    expect(XGetWMNormalHints(display, resize, &size_hints, &supplied_hints),
           "resize fixture has no WM_NORMAL_HINTS");
    expect((size_hints.flags & (PBaseSize | PResizeInc)) ==
               (PBaseSize | PResizeInc) &&
               size_hints.base_width == 40 && size_hints.base_height == 30 &&
               size_hints.width_inc == 13 && size_hints.height_inc == 7,
           "resize fixture increments or base size have drifted");
    pass("resize-increments");
    expect((size_hints.flags & PAspect) == PAspect &&
               size_hints.min_aspect.x == 4 &&
               size_hints.min_aspect.y == 3 &&
               size_hints.max_aspect.x == 16 &&
               size_hints.max_aspect.y == 9,
           "resize fixture aspect hints have drifted");
    pass("resize-aspect");

    verify_managed(display, "title", "title-managed");
    expect(XFetchName(display, title, &name) && name != NULL &&
               strcmp(name, initial_long_title) == 0 && strlen(name) > 200,
           "initial long WM_NAME was not preserved exactly");
    XFree(name);
    pass("title-initial-long");

    verify_managed(display, "icon", "icon-managed");
    expect(XGetIconName(display, icon, &icon_name) && icon_name != NULL &&
               strcmp(icon_name, "WTWM canonical icon name") == 0,
           "WM_ICON_NAME was not preserved exactly");
    XFree(icon_name);
    pass("icon-name");
    wm_hints = XGetWMHints(display, icon);
    expect(wm_hints != NULL &&
               (wm_hints->flags & (IconPixmapHint | IconMaskHint)) ==
                   (IconPixmapHint | IconMaskHint) &&
               wm_hints->icon_pixmap != wm_hints->icon_mask,
           "icon pixmap and mask hints are missing or not distinct");
    expect(pixmap_has_geometry(display, wm_hints->icon_pixmap, ICON_SIZE,
                               ICON_SIZE, 1),
           "icon pixmap is not a 16x16 depth-1 drawable");
    pass("icon-pixmap-depth1");
    expect(pixmap_has_geometry(display, wm_hints->icon_mask, ICON_SIZE,
                               ICON_SIZE, 1),
           "icon mask is not a 16x16 depth-1 drawable");
    pass("icon-mask-depth1");
    XFree(wm_hints);

    verify_managed(display, "urgent", "urgency-managed");
    wm_hints = XGetWMHints(display, urgent);
    expect(wm_hints != NULL &&
               (wm_hints->flags & (InputHint | XUrgencyHint)) ==
                   (InputHint | XUrgencyHint) &&
               wm_hints->input,
           "urgent fixture lacks XUrgencyHint or input capability");
    XFree(wm_hints);
    pass("urgency-hint");

    expect(XGetWindowAttributes(display, override, &attributes) &&
               attributes.override_redirect,
           "override fixture does not set override_redirect");
    pass("override-redirect");
    expect(query_parent(display, override, &parent) && parent == root,
           "override fixture was unexpectedly reparented");
    pass("override-root-parent");

    expect(window_has_class(display, legacy, LEGACY_NAME, LEGACY_CLASS),
           "legacy xterm WM_CLASS does not match the canonical selector");
    pass("legacy-xterm-class");
    expect(is_managed(display, legacy),
           "legacy xterm was not managed by reference twm");
    pass("legacy-xterm-managed");
}

static void
mutate_title(Display *display)
{
    XStoreName(display, find_role(display, "title"), mutated_title);
    XSync(display, False);
}

static void
focus_urgent(Display *display)
{
    XSetInputFocus(display, find_role(display, "urgent"), RevertToPointerRoot,
                   CurrentTime);
    XSync(display, False);
}

static void
verify_final(Display *display)
{
    Window title = find_role(display, "title");
    Window urgent = find_role(display, "urgent");
    Window focus = None;
    int revert_to = 0;
    char *name = NULL;

    expect(XFetchName(display, title, &name) && name != NULL &&
               strcmp(name, mutated_title) == 0,
           "mutated WM_NAME was not observed exactly");
    XFree(name);
    pass("title-mutated");

    XGetInputFocus(display, &focus, &revert_to);
    expect(focus == urgent && revert_to == RevertToPointerRoot,
           "explicit focus target or revert mode was not preserved");
    pass("focus-target-urgent");
}

static void
usage(void)
{
    fprintf(stderr,
            "usage: canonical-x11-client "
            "serve|wait|tag-legacy|verify-initial|mutate-title|focus-urgent|"
            "verify-final\n");
    exit(2);
}

int
main(int argc, char **argv)
{
    Display *display;

    if (argc != 2) {
        usage();
    }
    display = XOpenDisplay(NULL);
    if (display == NULL) {
        die("could not open DISPLAY");
    }

    if (strcmp(argv[1], "serve") == 0) {
        run_server(display);
    } else if (strcmp(argv[1], "wait") == 0) {
        wait_for_fixtures(display);
    } else if (strcmp(argv[1], "tag-legacy") == 0) {
        tag_legacy_xterm(display);
    } else if (strcmp(argv[1], "verify-initial") == 0) {
        verify_initial(display);
    } else if (strcmp(argv[1], "mutate-title") == 0) {
        mutate_title(display);
    } else if (strcmp(argv[1], "focus-urgent") == 0) {
        focus_urgent(display);
    } else if (strcmp(argv[1], "verify-final") == 0) {
        verify_final(display);
    } else {
        XCloseDisplay(display);
        usage();
    }
    XCloseDisplay(display);
    return 0;
}
