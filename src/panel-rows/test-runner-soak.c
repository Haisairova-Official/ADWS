/* Real JSON pipe -> rows renderer, used with either plugin supervisor backend.
 * Run in Xvfb: test-runner-soak SECONDS 'supervisor command'. */
#include "panel.c"
#include <stdio.h>
static gint64 began, previous, largest;
static guint samples, changes;
static long initial_rss, final_rss;
static Panel *panel;
static gint64 next_report;
static long rss_kib(void) {
    FILE *f=fopen("/proc/self/status","r");
    if(!f)return 0;
    char line[256]; long rss=0;
    while(fgets(line,sizeof(line),f))if(sscanf(line,"VmRSS: %ld",&rss)==1)break;
    fclose(f);return rss;
}
static void text_changed(GObject *o,GParamSpec *s,gpointer d) {
    (void)o;(void)s;(void)d;changes++;
}
static gboolean heartbeat(gpointer data) {
    (void)data;
    gint64 now=g_get_monotonic_time();
    if(now-began>3000000)largest=MAX(largest,now-previous);
    previous=now;samples++;
    final_rss=rss_kib();
    if(!initial_rss && now-began>10000000)initial_rss=final_rss;
    if(now>=next_report) {
        g_print("LYRICS_SOAK_PROGRESS elapsed_s=%lld changes=%u rss_kib=%ld max_gap_ms=%.2f\n",
            (long long)((now-began)/1000000),changes,final_rss,largest/1000.);
        next_report=now+60000000;
    }
    return G_SOURCE_CONTINUE;
}
static gboolean hover(gpointer data) {
    (void)data;
    show_controls(panel,!panel->controls_visible);
    if(panel->hover_source) {g_source_remove(panel->hover_source);panel->hover_source=0;}
    return G_SOURCE_CONTINUE;
}
static gboolean finish(gpointer data) {g_main_loop_quit(data);return G_SOURCE_REMOVE;}
int main(int argc,char **argv) {
    gtk_init(&argc,&argv);
    g_assert_cmpint(argc,==,3);
    GtkWidget *host=gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_widget_set_name(host,"waybar");
    const char *style=g_getenv("ADWS_SOAK_CSS");
    if(style && *style) {
        GtkCssProvider *css=gtk_css_provider_new();
        GError *error=NULL;
        g_assert_true(gtk_css_provider_load_from_path(css,style,&error));
        g_assert_no_error(error);
        gtk_style_context_add_provider_for_screen(gdk_screen_get_default(),GTK_STYLE_PROVIDER(css),GTK_STYLE_PROVIDER_PRIORITY_USER);
        g_object_unref(css);
    }
    GtkWidget *root=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0);
    gtk_container_add(GTK_CONTAINER(host),root);
    gtk_widget_set_size_request(host,-1,36);
    panel=create_widgets(GTK_CONTAINER(root),"custom-adws-org-AkiACG_Community-NCMLyricsBar",0);
    panel->animations=TRUE;
    panel->command=g_strdup(argv[2]);
    panel->previous_command=g_strdup("true");panel->next_command=g_strdup("true");
    enable_motion(panel);configure_controls(panel);
    g_signal_connect(panel->primary,"notify::label",G_CALLBACK(text_changed),NULL);
    gtk_widget_show_all(host);
    began=previous=g_get_monotonic_time();
    next_report=began+60000000;
    start(panel);
    gchar *pid=g_strdup(g_subprocess_get_identifier(panel->process));
    guint beat=g_timeout_add(20,heartbeat,NULL), hover_id=g_timeout_add(750,hover,NULL);
    GMainLoop *loop=g_main_loop_new(NULL,FALSE);
    g_timeout_add_seconds(atoi(argv[1]),finish,loop);
    g_main_loop_run(loop);
    g_assert_cmpstr(pid,==,g_subprocess_get_identifier(panel->process));
    g_assert_cmpuint(panel->retry,==,0);
    g_assert_cmpuint(changes,>,100);
    g_assert_cmpint(largest,<,700000);
    g_assert_cmpint(final_rss-initial_rss,<,32768);
    g_print("LYRICS_SOAK seconds=%s changes=%u heartbeats=%u max_gap_ms=%.2f rss_warm_kib=%ld rss_final_kib=%ld runner_restarts=0\n",argv[1],changes,samples,largest/1000.,initial_rss,final_rss);
    g_source_remove(beat);g_source_remove(hover_id);
    wbcffi_deinit(panel);gtk_widget_destroy(host);
    gint64 end=g_get_monotonic_time()+1000000;
    while(g_get_monotonic_time()<end){while(g_main_context_iteration(NULL,FALSE)){}g_usleep(1000);}
    g_free(pid);g_main_loop_unref(loop);return 0;
}
