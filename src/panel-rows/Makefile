CFLAGS += -O2 -Wall -Wextra -Werror -fPIC
GTK_FLAGS := $(shell pkg-config --cflags --libs gtk+-3.0 json-glib-1.0)

libmnws_panel.so: panel.c start-image.h motion.h
	$(CC) $(CFLAGS) -shared -o $@ $< $(GTK_FLAGS)

check: test-panel test-motion-events test-vertical
	xvfb-run -a env GDK_BACKEND=x11 ./test-panel
	xvfb-run -a env GDK_BACKEND=x11 ./test-motion-events
	xvfb-run -a env GDK_BACKEND=x11 ./test-vertical

test-panel: test-panel.c panel.c start-image.h motion.h
	$(CC) $(CFLAGS) -o $@ $< $(GTK_FLAGS)

test-motion-events: test-motion-events.c panel.c start-image.h motion.h
	$(CC) $(CFLAGS) -o $@ $< $(GTK_FLAGS)

test-vertical: test-vertical.c panel.c start-image.h motion.h
	$(CC) $(CFLAGS) -o $@ $< $(GTK_FLAGS)
