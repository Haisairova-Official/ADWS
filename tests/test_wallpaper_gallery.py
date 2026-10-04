import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import adws_wallpaper_gallery as gallery
from PIL import Image
from gi.repository import Gtk


class WallpaperLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root/'photo.png'
        Image.new('RGB',(400,200),'red').save(self.source)
        self.destination = self.root/'Wallpapers'

    def tearDown(self):
        self.temporary.cleanup()

    def test_explicit_default_directory(self):
        with patch.object(gallery.Path,'home',return_value=self.root):
            self.assertEqual(gallery.default_directory(),self.root/'Pictures/Wallpapers')
            self.assertFalse((self.root/'Pictures').exists())

    def test_thumbnail_preserves_aspect_and_bounds(self):
        width,height,data = gallery.thumbnail(self.source)
        self.assertEqual((width,height),(220,110))
        self.assertEqual(len(data),width*height*4)

    def test_import_uses_unique_names_and_never_overwrites(self):
        first = gallery.import_image(self.source,self.destination)
        before = first.read_bytes()
        Image.new('RGB',(64,64),'blue').save(self.source)
        second = gallery.import_image(self.source,self.destination)
        self.assertEqual(first.name,'photo.png')
        self.assertEqual(second.name,'photo (1).png')
        self.assertEqual(first.read_bytes(),before)
        self.assertNotEqual(second.read_bytes(),before)
        self.assertFalse(list(self.destination.glob('.wallpaper-import-*')))

    def test_import_already_in_library_is_not_duplicated(self):
        first = gallery.import_image(self.source,self.destination)
        self.assertEqual(gallery.import_image(first,self.destination),first.resolve())
        self.assertEqual(len(list(self.destination.iterdir())),1)

    def test_invalid_image_does_not_create_library(self):
        self.source.write_text('not an image')
        with self.assertRaises(Exception):
            gallery.import_image(self.source,self.destination)
        self.assertFalse(self.destination.exists())

    def test_failed_publication_removes_temporary_file(self):
        with patch.object(gallery,'_publish_without_replace',side_effect=PermissionError('read-only')):
            with self.assertRaises(PermissionError):
                gallery.import_image(self.source,self.destination)
        self.assertEqual(list(self.destination.iterdir()),[])

    def test_large_image_rejected_before_decode(self):
        with patch.object(gallery,'MAX_IMAGE_PIXELS',100):
            with self.assertRaises(ValueError):gallery.thumbnail(self.source)

    def test_raster_with_unknown_suffix_gets_discoverable_name(self):
        unknown = self.source.with_suffix('.image')
        self.source.rename(unknown)
        result = gallery.import_image(unknown,self.destination)
        self.assertEqual(result.name,'photo.png')
        self.assertEqual(gallery.scan_page(self.destination)[0],[result])

    def test_filesystem_without_hardlinks_uses_atomic_no_replace(self):
        import errno
        with patch.object(gallery.os,'link',side_effect=OSError(errno.EOPNOTSUPP,'unsupported')):
            first = gallery.import_image(self.source,self.destination)
            second = gallery.import_image(self.source,self.destination)
        self.assertEqual((first.name,second.name),('photo.png','photo (1).png'))
        self.assertEqual(first.read_bytes(),self.source.read_bytes())
        self.assertFalse(list(self.destination.glob('.wallpaper-import-*')))

    def test_paginated_scanning_is_sorted_and_excludes_links_and_hidden_files(self):
        self.destination.mkdir()
        for number in range(29):
            (self.destination/f'{number:02}.png').write_bytes(b'unvalidated until thumbnail')
        (self.destination/'noise.txt').write_text('ignored')
        (self.destination/'.private.png').write_text('ignored')
        (self.destination/'link.png').symlink_to(self.source)
        os.mkfifo(self.destination/'pipe.png')
        first,more = gallery.scan_page(self.destination,page=0)
        self.assertEqual([p.name for p in first],[f'{n:02}.png' for n in range(12)])
        self.assertTrue(more)
        last,more = gallery.scan_page(self.destination,page=2)
        self.assertEqual([p.name for p in last],[f'{n:02}.png' for n in range(24,29)])
        self.assertFalse(more)

    def test_cancelled_scan_returns_no_paths(self):
        event = threading.Event();event.set()
        self.assertEqual(gallery.scan_page(self.root,cancelled=event),([],False))

    def test_new_image_can_be_located_on_later_page(self):
        self.destination.mkdir()
        for index in range(30):
            (self.destination/f'{index:02}.png').write_bytes(b'placeholder')
        self.assertEqual(gallery.page_containing(self.destination,self.destination/'29.png'),2)

    def test_directory_saved_only_by_explicit_call(self):
        target = self.root/'config/adws/wallpaper-library.json'
        with patch.object(gallery,'library_config_path',return_value=target):
            self.assertEqual(gallery.library_directory(),gallery.default_directory())
            self.assertFalse(target.exists())
            gallery.save_directory(self.root)
            self.assertEqual(gallery.library_directory(),self.root)
            self.assertFalse(list(target.parent.glob('.wallpaper-library-*')))


@unittest.skipUnless(Gtk.init_check()[0], 'GTK display required')
class WallpaperGalleryInteractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.library = self.root/'Wallpapers';self.library.mkdir()
        self.image = self.library/'one.png'
        Image.new('RGB',(400,200),'green').save(self.image)
        self.selections = []
        with patch.object(gallery,'library_directory',return_value=self.library):
            self.widget = gallery.WallpaperGallery(self.selections.append,initial_path=self.image)
        self.window = Gtk.Window();self.window.add(self.widget);self.window.show_all()
        self.wait_until(lambda: str(self.image) in self.widget.tiles and self.widget.tiles[str(self.image)].thumbnail_image.get_pixbuf() is not None)

    def tearDown(self):
        self.window.destroy()
        self.widget.executor.shutdown(wait=True)
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        self.temporary.cleanup()

    def wait_until(self, predicate):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            while Gtk.events_pending():Gtk.main_iteration_do(False)
            if predicate():return
            time.sleep(.01)
        self.fail('Gallery did not complete the asynchronous operation')

    def test_initial_selection_does_not_emit_or_apply_and_click_emits_once(self):
        self.assertEqual(self.selections,[])
        self.assertEqual(self.widget.get_filename(),str(self.image))
        signals = []
        self.widget.connect('selection-changed',lambda widget,path:signals.append(path))
        self.widget.tiles[str(self.image)].clicked()
        self.assertEqual(self.selections,[str(self.image)])
        self.assertEqual(signals,[str(self.image)])

    def test_explicit_import_is_selected_after_atomic_copy(self):
        source = self.root/'other.png'
        Image.new('RGB',(30,20),'blue').save(source)
        self.widget.import_paths([source])
        self.wait_until(lambda:not self.widget.importing and self.widget.get_filename()==str(self.library/'other.png'))
        self.assertTrue((self.library/'other.png').exists())
        self.assertEqual(self.selections,[str(self.library/'other.png')])
        self.assertFalse(list(self.library.glob('.wallpaper-import-*')))

    def test_stale_thumbnail_callbacks_do_not_replace_current_page(self):
        token = self.widget.cancelled
        self.widget.refresh()
        self.assertTrue(token.is_set())
        self.widget.show_paths(token,[self.root/'stale.png'],False)
        self.assertNotIn(str(self.root/'stale.png'),self.widget.tiles)

    def test_destroyed_gallery_ignores_queued_result(self):
        self.window.destroy()
        self.assertFalse(self.widget.alive)
        self.assertFalse(self.widget.show_paths(threading.Event(),[self.image],False))


if __name__=='__main__':
    unittest.main()
