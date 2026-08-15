#define _POSIX_C_SOURCE 200809L

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ROLE_PROPERTY "_WTWM_REFERENCE_ROLE"
#define READY_PROPERTY "_WTWM_REFERENCE_READY"
#define ROLE_COUNT 2

struct controlled_window {
    const char *role;
    Window client;
    Window frame;
};

static const char *const roles[ROLE_COUNT] = {"alpha", "bravo"};

static _Noreturn void
die(const char *message)
{
    fprintf(stderr, "reference capture client: %s\n", message);
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

static unsigned long
named_pixel(Display *display, const char *name)
{
    int screen = DefaultScreen(display);
    XColor exact;
    XColor screen_color;

    if (!XAllocNamedColor(display, DefaultColormap(display, screen), name,
                          &screen_color, &exact)) {
        die("could not allocate a scenario color");
    }
    return screen_color.pixel;
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

    if (XGetWindowProperty(display, window, role_atom, 0, 32, False, XA_STRING,
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
    char role[32];
    unsigned int i;

    if (read_role(display, window, role, sizeof(role)) &&
        strcmp(role, wanted) == 0) {
        *result = window;
        return 1;
    }
    if (depth == 0 || !XQueryTree(display, window, &root, &parent, &children,
                                  &child_count)) {
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
find_frame(Display *display, Window root, Window client)
{
    Window current = client;

    for (;;) {
        Window query_root;
        Window parent;
        Window *children = NULL;
        unsigned int child_count = 0;

        if (!XQueryTree(display, current, &query_root, &parent, &children,
                        &child_count)) {
            die("could not query a controlled window parent");
        }
        if (children != NULL) {
            XFree(children);
        }
        if (parent == root) {
            return current;
        }
        if (parent == None || parent == current) {
            die("controlled window has no root ancestor");
        }
        current = parent;
    }
}

static int
find_controlled_windows(Display *display,
                        struct controlled_window windows[ROLE_COUNT])
{
    Window root = DefaultRootWindow(display);
    int i;

    for (i = 0; i < ROLE_COUNT; i++) {
        windows[i].role = roles[i];
        windows[i].client = None;
        windows[i].frame = None;
        if (!find_role_recursive(display, root, roles[i], 5,
                                 &windows[i].client)) {
            return 0;
        }
        windows[i].frame = find_frame(display, root, windows[i].client);
    }
    return 1;
}

static void
set_window_metadata(Display *display, Window window, const char *role,
                    const char *title, int x, int y, int width, int height)
{
    XClassHint class_hint;
    XSizeHints size_hints;
    XWMHints wm_hints;

    XStoreName(display, window, title);
    XSetIconName(display, window, title);
    class_hint.res_name = (char *) role;
    class_hint.res_class = (char *) "WtwmReference";
    XSetClassHint(display, window, &class_hint);

    memset(&size_hints, 0, sizeof(size_hints));
    size_hints.flags = USPosition | USSize;
    size_hints.x = x;
    size_hints.y = y;
    size_hints.width = width;
    size_hints.height = height;
    XSetWMNormalHints(display, window, &size_hints);

    memset(&wm_hints, 0, sizeof(wm_hints));
    wm_hints.flags = InputHint;
    wm_hints.input = True;
    XSetWMHints(display, window, &wm_hints);
    set_role(display, window, role);
}

static void
draw_scenario(Display *display, Window alpha, Window bravo,
              unsigned long alpha_accent, unsigned long bravo_accent)
{
    GC gc = XCreateGC(display, alpha, 0, NULL);

    XSetForeground(display, gc, alpha_accent);
    XFillRectangle(display, alpha, gc, 8, 8, 52, 14);
    XFillRectangle(display, alpha, gc, 24, 30, 64, 20);
    XSetForeground(display, gc, bravo_accent);
    XFillRectangle(display, bravo, gc, 10, 10, 72, 16);
    XFillRectangle(display, bravo, gc, 42, 34, 56, 22);
    XFreeGC(display, gc);
}

static int
windows_are_managed(Display *display)
{
    struct controlled_window windows[ROLE_COUNT];

    return find_controlled_windows(display, windows) &&
           windows[0].frame != windows[0].client &&
           windows[1].frame != windows[1].client;
}

static void
run_scenario(Display *display)
{
    Window root = DefaultRootWindow(display);
    unsigned long black = named_pixel(display, "#101010");
    unsigned long root_color = named_pixel(display, "#303030");
    unsigned long alpha_color = named_pixel(display, "#286090");
    unsigned long bravo_color = named_pixel(display, "#904828");
    unsigned long alpha_accent = named_pixel(display, "#78c8ff");
    unsigned long bravo_accent = named_pixel(display, "#ffc078");
    Window alpha;
    Window bravo;
    Atom ready_atom = XInternAtom(display, READY_PROPERTY, False);
    unsigned long ready = 1;
    int attempt;

    XSetWindowBackground(display, root, root_color);
    XClearWindow(display, root);

    alpha = XCreateSimpleWindow(display, root, 30, 28, 100, 65, 0, black,
                                alpha_color);
    bravo = XCreateSimpleWindow(display, root, 88, 58, 110, 70, 0, black,
                                bravo_color);
    set_window_metadata(display, alpha, "alpha", "Reference Alpha", 30, 28,
                        100, 65);
    set_window_metadata(display, bravo, "bravo", "Reference Bravo", 88, 58,
                        110, 70);
    XSelectInput(display, alpha, ExposureMask | StructureNotifyMask);
    XSelectInput(display, bravo, ExposureMask | StructureNotifyMask);

    XMapWindow(display, alpha);
    XSync(display, False);
    pause_milliseconds(100);
    XMapWindow(display, bravo);
    XSync(display, False);

    for (attempt = 0; attempt < 100; attempt++) {
        if (windows_are_managed(display)) {
            break;
        }
        pause_milliseconds(50);
    }
    if (!windows_are_managed(display)) {
        die("scenario windows were not managed by twm");
    }

    XClearWindow(display, alpha);
    XClearWindow(display, bravo);
    draw_scenario(display, alpha, bravo, alpha_accent, bravo_accent);
    XChangeProperty(display, root, ready_atom, XA_CARDINAL, 32, PropModeReplace,
                    (const unsigned char *) &ready, 1);
    XSync(display, False);

    for (;;) {
        XEvent event;

        XNextEvent(display, &event);
        if (event.type == Expose && event.xexpose.count == 0) {
            draw_scenario(display, alpha, bravo, alpha_accent, bravo_accent);
            XFlush(display);
        }
    }
}

static void
wait_for_scenario(Display *display)
{
    Window root = DefaultRootWindow(display);
    Atom ready_atom = XInternAtom(display, READY_PROPERTY, False);
    int attempt;

    for (attempt = 0; attempt < 100; attempt++) {
        Atom actual_type;
        int actual_format;
        unsigned long item_count;
        unsigned long bytes_after;
        unsigned char *data = NULL;
        int ready = 0;

        if (XGetWindowProperty(display, root, ready_atom, 0, 1, False,
                               XA_CARDINAL, &actual_type, &actual_format,
                               &item_count, &bytes_after, &data) == Success &&
            actual_type == XA_CARDINAL && actual_format == 32 &&
            item_count == 1) {
            ready = 1;
        }
        if (data != NULL) {
            XFree(data);
        }
        if (ready && windows_are_managed(display)) {
            return;
        }
        pause_milliseconds(50);
    }
    die("scenario did not become ready");
}

static struct controlled_window *
window_for_role(struct controlled_window windows[ROLE_COUNT], const char *role)
{
    int i;

    for (i = 0; i < ROLE_COUNT; i++) {
        if (strcmp(windows[i].role, role) == 0) {
            return &windows[i];
        }
    }
    return NULL;
}

static void
set_phase(Display *display, const char *role)
{
    struct controlled_window windows[ROLE_COUNT];
    struct controlled_window *target;

    if (!find_controlled_windows(display, windows)) {
        die("could not find controlled windows for phase change");
    }
    target = window_for_role(windows, role);
    if (target == NULL) {
        die("phase role must be alpha or bravo");
    }
    XRaiseWindow(display, target->frame);
    XSync(display, False);
    pause_milliseconds(250);
    XSetInputFocus(display, target->client, RevertToPointerRoot, CurrentTime);
    XSync(display, False);
    pause_milliseconds(250);
}

static const char *
focus_name(Window focus, struct controlled_window windows[ROLE_COUNT])
{
    int i;

    if (focus == None) {
        return "None";
    }
    if (focus == PointerRoot) {
        return "PointerRoot";
    }
    for (i = 0; i < ROLE_COUNT; i++) {
        if (focus == windows[i].client) {
            return windows[i].role;
        }
    }
    return "Unrecognized";
}

static const char *
revert_name(int revert_to)
{
    switch (revert_to) {
    case RevertToNone:
        return "None";
    case RevertToPointerRoot:
        return "PointerRoot";
    case RevertToParent:
        return "Parent";
    default:
        return "Unrecognized";
    }
}

static void
write_geometry(FILE *output, Display *display, Window root, Window window)
{
    XWindowAttributes attributes;
    Window child;
    int root_x;
    int root_y;

    if (!XGetWindowAttributes(display, window, &attributes) ||
        !XTranslateCoordinates(display, window, root, 0, 0, &root_x, &root_y,
                               &child)) {
        die("could not read controlled window geometry");
    }
    fprintf(output, "%d\t%d\t%d\t%d\t%d\t%s", root_x, root_y,
            attributes.width, attributes.height, attributes.border_width,
            attributes.map_state == IsViewable ? "viewable" : "not-viewable");
}

static void
capture_state(Display *display, const char *output_path)
{
    Window root = DefaultRootWindow(display);
    struct controlled_window windows[ROLE_COUNT];
    XWindowAttributes root_attributes;
    Window focus;
    int revert_to;
    Window query_root;
    Window parent;
    Window *children = NULL;
    unsigned int child_count = 0;
    const char *stack[ROLE_COUNT];
    int stack_count = 0;
    unsigned int i;
    FILE *output;

    if (!find_controlled_windows(display, windows)) {
        die("could not find controlled windows for capture");
    }
    if (!XGetWindowAttributes(display, root, &root_attributes)) {
        die("could not read root geometry");
    }
    XGetInputFocus(display, &focus, &revert_to);
    if (!XQueryTree(display, root, &query_root, &parent, &children,
                    &child_count)) {
        die("could not read root stacking order");
    }
    for (i = 0; i < child_count; i++) {
        int role_index;

        for (role_index = 0; role_index < ROLE_COUNT; role_index++) {
            if (children[i] == windows[role_index].frame) {
                stack[stack_count++] = windows[role_index].role;
            }
        }
    }
    if (children != NULL) {
        XFree(children);
    }
    if (stack_count != ROLE_COUNT) {
        die("root stacking order omitted a controlled frame");
    }

    output = fopen(output_path, "w");
    if (output == NULL) {
        die("could not open state output");
    }
    fprintf(output, "screen\t%d\t%d\t%d\n", root_attributes.width,
            root_attributes.height, root_attributes.depth);
    fprintf(output, "focus\t%s\t%s\n", focus_name(focus, windows),
            revert_name(revert_to));
    fprintf(output, "stack\t%s\t%s\n", stack[0], stack[1]);
    for (i = 0; i < ROLE_COUNT; i++) {
        fprintf(output, "window\t%s\tclient\t", windows[i].role);
        write_geometry(output, display, root, windows[i].client);
        fprintf(output, "\tframe\t");
        write_geometry(output, display, root, windows[i].frame);
        fputc('\n', output);
    }
    if (fclose(output) != 0) {
        die("could not close state output");
    }
}

static _Noreturn void
usage(const char *program)
{
    fprintf(stderr,
            "usage: %s scenario | wait | set-phase ROLE | capture OUTPUT\n",
            program);
    exit(EXIT_FAILURE);
}

int
main(int argc, char **argv)
{
    Display *display = XOpenDisplay(NULL);

    if (display == NULL) {
        die("could not open DISPLAY");
    }
    if (argc == 2 && strcmp(argv[1], "scenario") == 0) {
        run_scenario(display);
    }
    else if (argc == 2 && strcmp(argv[1], "wait") == 0) {
        wait_for_scenario(display);
    }
    else if (argc == 3 && strcmp(argv[1], "set-phase") == 0) {
        set_phase(display, argv[2]);
    }
    else if (argc == 3 && strcmp(argv[1], "capture") == 0) {
        capture_state(display, argv[2]);
    }
    else {
        XCloseDisplay(display);
        usage(argv[0]);
    }
    XCloseDisplay(display);
    return EXIT_SUCCESS;
}
