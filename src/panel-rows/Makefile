CFLAGS += -O2 -Wall -Wextra -Werror -fPIC
GTK_FLAGS := $(shell pkg-config --cflags --libs gtk+-3.0 json-glib-1.0)

libmnws_panel.so: panel.c start-image.h
	$(CC) $(CFLAGS) -shared -o $@ $< $(GTK_FLAGS)

check: test-panel
	xvfb-run -a env GDK_BACKEND=x11 ./test-panel

test-panel: test-panel.c panel.c start-image.h
	$(CC) $(CFLAGS) -o $@ $< $(GTK_FLAGS)
