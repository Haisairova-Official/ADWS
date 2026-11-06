import json,os,pty,signal,sys,tempfile,tomllib,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import adws_palette_sync as palette

class PaletteSyncTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.config=self.root/'config';self.data=self.root/'data';self.home=self.root/'home';self.home.mkdir()
  self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.config),'XDG_DATA_HOME':str(self.data),'XDG_STATE_HOME':str(self.root/'state')});self.env.start();self.addCleanup(self.env.stop)
  self.colors=dict(palette.DEFAULT_PALETTE)
 def write(self,relative,text):
  p=self.config/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def plan(self,targets,**kwargs):return palette.registration_plan(targets,config_home=self.config,data_home=self.data,home=self.home,**kwargs)
 def install(self,targets,**kwargs):
  plan=self.plan(targets,**kwargs);self.assertFalse(plan['conflicts']);palette.register(plan,self.root/'backup',runner=Mock(return_value=Mock(returncode=0,stdout='',stderr='')),foot_binary='/fixture/foot');return json.loads(palette.registry_path().read_text())
 def test_unregistered_never_calls_runtime_or_changes_files(self):
  runner=Mock();result=palette.synchronize(self.colors,runner=runner)
  self.assertEqual(result['status'],'not-registered');runner.assert_not_called();self.assertFalse(self.config.exists())
 def test_review_then_registration_preserves_non_color_kitty_settings(self):
  main=self.write('kitty/kitty.conf','font_family Custom Font\nfont_size 15\nbackground #123456\n')
  plan=self.plan(['kitty']);self.assertNotIn('ADWS',main.read_text());palette.register(plan,self.root/'backup')
  self.assertIn('font_size 15',main.read_text());self.assertIn('include ',main.read_text())
  self.assertTrue(palette.registry_path().exists())
  self.assertEqual(palette.rollback_registration(self.root/'backup')['status'],'restored')
  self.assertEqual(main.read_text(),'font_family Custom Font\nfont_size 15\nbackground #123456\n')
  self.assertFalse(palette.registry_path().exists())
 def test_kitty_reload_only_matching_user_processes_no_shell(self):
  reg=self.install(['kitty']);runner=Mock();send=Mock()
  find=Mock(return_value=[(11,['kitty']),(12,['kitty','--config','/other/kitty.conf'])])
  result=palette.synchronize(self.colors,reg,runner=runner,process_finder=find,signaler=send)
  send.assert_called_once_with(11,signal.SIGUSR1);runner.assert_not_called()
  self.assertEqual(result['targets']['kitty']['custom_config_skipped'],1)
 def test_alacritty_preserves_settings_and_requires_inline_color_approval(self):
  self.write('alacritty/alacritty.toml','[font]\nsize=17\n[general]\nimport=["custom.toml"]\n[colors.primary]\nbackground="#abcdef"\n')
  self.assertTrue(self.plan(['alacritty'])['conflicts'])
  reg=self.install(['alacritty'],replace_colors=True)
  actual=tomllib.loads((self.config/'alacritty/alacritty.toml').read_text());self.assertEqual(actual['font']['size'],17);self.assertNotIn('colors',actual)
  self.assertEqual(actual['general']['import'][0],'custom.toml')
  result=palette.synchronize(self.colors,reg,runner=Mock(),process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['targets']['alacritty']['status'],'file-watch')
 def test_alacritty_disabled_reload_is_not_false_success(self):
  self.write('alacritty/alacritty.toml','[general]\nlive_config_reload=false\n')
  self.assertTrue(self.plan(['alacritty'])['conflicts'])
 def test_mako_includes_before_user_criteria_and_actual_reload(self):
  self.write('mako/config','font=Custom 14\n[app-name=test]\nbackground-color=#ff0000\n')
  reg=self.install(['mako']);text=(self.config/'mako/config').read_text()
  self.assertLess(text.index('include='),text.index('[app-name'));self.assertIn('font=Custom 14',text)
  runner=Mock(return_value=Mock(returncode=0))
  report=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[(22,['mako'])],signaler=Mock())
  self.assertEqual(report['targets']['mako']['status'],'reload-requested')
  self.assertEqual(runner.call_args.args[0],['makoctl','reload'])
 def test_dunst_dropin_and_reload(self):
  self.write('dunst/dunstrc','[global]\nfont=Custom 14\n')
  reg=self.install(['dunst']);runner=Mock(return_value=Mock(returncode=0))
  palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[(23,['dunst'])],signaler=Mock())
  self.assertEqual(runner.call_args.args[0],['dunstctl','reload']);self.assertIn('font=Custom 14',(self.config/'dunst/dunstrc').read_text())
 def test_custom_notification_config_is_preserved_and_reported(self):
  reg=self.install(['mako']);runner=Mock()
  report=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[(22,['mako','--config','/custom/notification.conf'])],signaler=Mock())
  self.assertEqual(report['status'],'partial');self.assertEqual(report['targets']['mako']['status'],'manual');runner.assert_not_called()
 def test_icons_inherit_original_theme_and_alternate_without_copying_application_icons(self):
  self.write('gtk-3.0/settings.ini','[Settings]\ngtk-font-name=User Font 11\n')
  reg=self.install(['icons'],base_icon_theme='UserTheme');active=['UserTheme'];commands=[]
  def run(argv,**_):
   commands.append(argv)
   if argv[1]=='get':return Mock(stdout=repr(active[0]),returncode=0)
   active[0]=argv[-1];return Mock(returncode=0)
  for expected in ('ADWS-Palette-A','ADWS-Palette-B','ADWS-Palette-A'):
   report=palette.synchronize(self.colors,reg,runner=run,process_finder=lambda _:[],signaler=Mock())
   self.assertEqual(active[0],expected);self.assertEqual(report['targets']['icons']['status'],'theme-notified')
   theme=self.data/'icons'/expected
   self.assertIn('Inherits=UserTheme,hicolor',(theme/'index.theme').read_text())
   self.assertEqual([p.name for p in (theme/'scalable/apps').iterdir()],['application-x-executable.svg'])
   self.assertIn('User Font 11',(self.config/'gtk-3.0/settings.ini').read_text())
 def test_external_icon_theme_change_stops_automatic_override(self):
  reg=self.install(['icons'],base_icon_theme='UserTheme');runner=Mock(return_value=Mock(stdout="'DifferentTheme'"))
  result=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(runner.call_count,1);self.assertFalse((self.data/'icons').exists())
 def test_user_edits_managed_fragment_are_not_overwritten(self):
  reg=self.install(['kitty']);fragment=Path(reg['managed']['kitty']['fragment']);fragment.write_text('my custom theme')
  result=palette.synchronize(self.colors,reg,runner=Mock(),process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(fragment.read_text(),'my custom theme')
 def test_stale_registration_plan_rejected(self):
  main=self.write('kitty/kitty.conf','font_size 10\n');plan=self.plan(['kitty']);main.write_text('font_size 20\n')
  with self.assertRaises(ValueError):palette.register(plan,self.root/'backup')
  self.assertEqual(main.read_text(),'font_size 20\n')
 def test_foot_hook_requires_explicit_shell_and_writes_only_own_terminal(self):
  self.assertIn('next-launch-only',[row['status'] for row in self.plan(['foot'])['limitations']])
  reg=self.install(['foot'],foot_shell='bash')
  self.assertIn('ADWS PALETTE',(self.home/'.bashrc').read_text())
  data=self.config/'adws/palette/foot.json';master,slave=pty.openpty()
  try:
   with patch.dict(os.environ,{'TERM':'foot'}):palette.watch_foot(data,os.getpid(),tty_fd=slave,once=True)
   self.assertEqual(os.read(master,4096),palette.foot_sequences(self.colors))
  finally:os.close(master);os.close(slave)
 def test_foot_fresh_blank_shell_keeps_next_launch_only(self):
  proposal=self.plan(['foot'])
  self.assertIsNone(proposal['foot_shell'])
  self.assertIn('next-launch-only',[row['status'] for row in proposal['limitations']])
  self.assertFalse(any(Path(row['path']).name in ('foot-hook.sh','.bashrc','.zshrc') for row in proposal['files']))
  reg=self.install(['foot'])
  self.assertIsNone(reg['foot_shell']);self.assertFalse((self.config/'adws/palette/foot-hook.sh').exists())
 def test_foot_existing_blank_shell_preserves_hook_and_relocates_source(self):
  rc=self.home/'.bashrc';rc.write_text('alias mine="echo user"\n')
  old_source=self.root/'old source 源/tools/adws_palette_sync.py'
  with patch.object(palette,'__file__',str(old_source)):
   self.install(['foot'],foot_shell='bash')
  hook=self.config/'adws/palette/foot-hook.sh';before=hook.read_text()
  self.assertIn(str(old_source),before)
  proposal=self.plan(['foot'])
  self.assertFalse(proposal['conflicts']);self.assertEqual(proposal['foot_shell'],'bash')
  self.assertEqual(proposal['foot_shell_policy'],'preserve-registered')
  palette.register(proposal,self.root/'second-backup',runner=Mock(return_value=Mock(returncode=0,stdout='',stderr='')),foot_binary='/fixture/foot')
  self.assertNotIn(str(old_source),hook.read_text());self.assertIn(str(Path(palette.__file__).resolve()),hook.read_text())
  self.assertIn('alias mine="echo user"',rc.read_text());self.assertEqual(rc.read_text().count(palette.BEGIN),1)
  self.assertEqual(json.loads(palette.registry_path().read_text())['foot_shell'],'bash')
  self.assertEqual(palette.rollback_registration(self.root/'second-backup')['status'],'restored')
  self.assertEqual(hook.read_text(),before)
 def test_foot_explicit_shell_overrides_inheritance(self):
  self.install(['foot'],foot_shell='bash');proposal=self.plan(['foot'],foot_shell='zsh')
  self.assertFalse(proposal['conflicts']);self.assertEqual(proposal['foot_shell'],'zsh')
  self.assertTrue(any(row['path']==str(self.home/'.zshrc') for row in proposal['files']))
 def test_foot_user_edited_hook_is_preserved_even_with_marker(self):
  self.install(['foot'],foot_shell='bash');hook=self.config/'adws/palette/foot-hook.sh'
  hook.write_text(hook.read_text()+'# My extension\nexport MY_FOOT_OPTION=1\n');before=hook.read_bytes()
  for shell in (None,'bash','zsh'):
   with self.subTest(shell=shell):
    proposal=self.plan(['foot'],foot_shell=shell)
    self.assertTrue(any('User-edited Foot hook' in row['reason'] for row in proposal['conflicts']))
    with self.assertRaisesRegex(ValueError,'conflicts'):palette.register(proposal,self.root/'second-backup')
    self.assertEqual(hook.read_bytes(),before);self.assertFalse((self.root/'second-backup').exists())
 def test_foot_existing_hook_without_registration_is_not_silently_disabled(self):
  self.install(['foot'],foot_shell='bash');palette.registry_path().unlink()
  proposal=self.plan(['foot']);self.assertTrue(any('matching shell registration' in row['reason'] for row in proposal['conflicts']))
  self.assertFalse(self.plan(['foot'],foot_shell='bash')['conflicts'])
 def test_foot_user_commands_inside_shell_integration_are_not_erased(self):
  self.install(['foot'],foot_shell='bash');rc=self.home/'.bashrc'
  rc.write_text(rc.read_text().replace(palette.END,'export MY_FOOT_OPTION=1\n'+palette.END));before=rc.read_bytes()
  proposal=self.plan(['foot']);self.assertTrue(any('shell integration requires review' in row['reason'] for row in proposal['conflicts']))
  with self.assertRaisesRegex(ValueError,'conflicts'):palette.register(proposal,self.root/'second-backup')
  self.assertEqual(rc.read_bytes(),before)
 def test_registry_changed_after_preview_is_rejected_before_parser_or_writes(self):
  self.install(['foot'],foot_shell='bash');proposal=self.plan(['foot'])
  registration=palette.registry_path();content=json.loads(registration.read_text());content['foot_shell']='zsh'
  registration.write_text(json.dumps(content));before={p:p.read_bytes() for p in self.config.rglob('*') if p.is_file()}
  runner=Mock(side_effect=AssertionError('Changed review must not reach installed parser'))
  with self.assertRaisesRegex(ValueError,'registration changed after review'):
   palette.register(proposal,self.root/'second-backup',runner=runner,foot_binary='/fixture/foot')
  runner.assert_not_called();self.assertFalse((self.root/'second-backup').exists())
  self.assertEqual(before,{p:p.read_bytes() for p in self.config.rglob('*') if p.is_file()})
 def test_malformed_registry_is_not_replaced(self):
  registration=self.write('adws/palette-sync.json','{broken');proposal=self.plan(['kitty'])
  self.assertTrue(proposal['conflicts'])
  with self.assertRaisesRegex(ValueError,'conflicts'):palette.register(proposal,self.root/'backup')
  self.assertEqual(registration.read_text(),'{broken');self.assertFalse((self.root/'backup').exists())
 def test_foot_registration_does_not_claim_unstarted_hooks_are_live(self):
  reg=self.install(['foot'],foot_shell='bash')
  with patch.object(palette,'foot_watchers',return_value=[]):
   result=palette.synchronize(self.colors,reg,runner=Mock(),process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(result['targets']['foot']['status'],'hook-activation-pending')
  with patch.object(palette,'foot_watchers',return_value=[123]):
   result=palette.synchronize(self.colors,reg,runner=Mock(),process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['targets']['foot']['status'],'file-watch')
 def test_foot_format_is_reviewed_before_installed_parser_resolution(self):
  with patch.object(palette.shutil,'which',side_effect=AssertionError('Planning must not require Foot already installed')):
   proposal=self.plan(['foot'],foot_shell='bash')
  self.assertEqual(set(proposal['foot_format_alternatives']),{'colors-dark','colors'})
  self.assertIn('format-check-after-dependencies',[row['status'] for row in proposal['limitations']])
  original_files=[dict(row) for row in proposal['files']]
  seen=[]
  def old_foot(argv,**kwargs):
   main=Path(argv[-1]).read_text();fragment=Path(next(line[8:] for line in main.splitlines() if line.startswith('include=')))
   data=fragment.read_text();seen.append(data)
   return Mock(returncode=230 if '[colors-dark]' in data else 0,stdout='',stderr='unsupported modern section' if '[colors-dark]' in data else '')
  resolved=palette.resolve_foot_plan(proposal,runner=old_foot,foot_binary='/fixture/old-foot')
  self.assertEqual(resolved['managed']['foot']['section'],'colors')
  self.assertEqual(proposal['files'],original_files)
  self.assertEqual(len(seen),2)
  # Only the approved fragment's section differs; user file proposals are exact.
  for old,new in zip(proposal['files'],resolved['files']):
   if old['path']!=proposal['managed']['foot']['fragment']:self.assertEqual(old,new)
 def test_actual_parser_rejection_leaves_all_targets_and_backup_unmodified(self):
  original=self.write('kitty/kitty.conf','font_size 17\n');proposal=self.plan(['kitty','foot'])
  with self.assertRaisesRegex(ValueError,'rejected the reviewed complete configuration'):
   palette.register(proposal,self.root/'backup',runner=Mock(return_value=Mock(returncode=230,stdout='',stderr='invalid existing user setting')),foot_binary='/fixture/foot')
  self.assertEqual(original.read_text(),'font_size 17\n');self.assertFalse((self.root/'backup').exists());self.assertFalse(palette.registry_path().exists())
 def test_foot_registration_persists_resolved_section_for_future_updates(self):
  reg=self.install(['foot'],foot_shell='bash')
  self.assertEqual(reg['managed']['foot']['section'],'colors-dark')
  self.assertEqual(reg['foot_format_resolution']['section'],'colors-dark')
  palette.synchronize(self.colors,reg,process_finder=lambda _:[],signaler=Mock())
  fragment=Path(reg['managed']['foot']['fragment'])
  self.assertIn('[colors-dark]',fragment.read_text());self.assertNotIn('[colors]\n',fragment.read_text())
 def test_foot_probe_validates_complete_reviewed_main_and_existing_includes(self):
  existing=self.write('foot/personal.ini','[main]\nfont=Custom 12\n')
  self.write('foot/foot.ini','font=UserFont 14\ninclude='+str(existing)+'\n')
  def check(argv,**kwargs):
   content=Path(argv[-1]).read_text()
   self.assertIn('font=UserFont 14',content);self.assertIn('include='+str(existing),content)
   self.assertEqual(argv[1:3],['--check-config','--config'])
   return Mock(returncode=0,stdout='',stderr='')
  palette.register(self.plan(['foot']),self.root/'backup',runner=check,foot_binary='/fixture/foot')
  self.assertEqual(existing.read_text(),'[main]\nfont=Custom 12\n')
 def test_foot_probe_requires_installed_binary_and_reviewed_policy(self):
  proposal=self.plan(['foot'])
  with patch.object(palette.shutil,'which',return_value=None),self.assertRaisesRegex(ValueError,'Install Foot'):
   palette.register(proposal,self.root/'backup')
  proposal.pop('foot_format_policy')
  with self.assertRaisesRegex(ValueError,'Review Foot'):
   palette.register(proposal,self.root/'backup',foot_binary='/fixture/foot')
 def test_controlling_tty_mux_is_not_rejected_for_system_owned_device_node(self):
  data=self.write('palette.json',json.dumps(self.colors));master,slave=pty.openpty();owned=os.dup(slave)
  actual=os.fstat(owned)
  try:
   with patch.dict(os.environ,{'TERM':'foot'}),patch.object(palette.os,'open',return_value=owned),patch.object(palette.os,'fstat',return_value=Mock(st_mode=actual.st_mode,st_uid=os.getuid()+1)):
    palette.watch_foot(data,os.getpid(),once=True)
   self.assertEqual(os.read(master,4096),palette.foot_sequences(self.colors))
  finally:os.close(master);os.close(slave)
 def test_unresolved_old_foot_registry_is_reported_without_writing_bad_section(self):
  reg=self.install(['foot']);reg['managed']['foot'].pop('section');fragment=Path(reg['managed']['foot']['fragment']);before=fragment.read_bytes()
  report=palette.synchronize(self.colors,reg)
  self.assertEqual(report['targets']['foot']['status'],'failed');self.assertEqual(fragment.read_bytes(),before)
 def test_icon_name_collision_does_not_switch_theme(self):
  reg=self.install(['icons'],base_icon_theme='UserTheme')
  index=self.data/'icons/ADWS-Palette-A/index.theme';index.parent.mkdir(parents=True);index.write_text('[Icon Theme]\nName=User icon theme\n')
  runner=Mock(return_value=Mock(stdout="'UserTheme'"))
  result=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(runner.call_count,1)
  self.assertIn('User icon theme',index.read_text())
 def test_malformed_gtk_config_preserves_theme_and_existing_files(self):
  reg=self.install(['icons'],base_icon_theme='UserTheme');self.write('gtk-3.0/settings.ini','broken settings')
  runner=Mock(return_value=Mock(stdout="'UserTheme'"))
  result=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(runner.call_count,1)
  self.assertFalse((self.data/'icons').exists())
 def test_registration_rollback_preserves_user_retargeted_symlink(self):
  real=self.write('real-kitty.conf','font_size 12\n');main=self.config/'kitty/kitty.conf';main.parent.mkdir();main.symlink_to(real)
  plan=self.plan(['kitty']);palette.register(plan,self.root/'backup')
  unrelated=self.write('other-kitty.conf',real.read_text());main.unlink();main.symlink_to(unrelated)
  report=palette.rollback_registration(self.root/'backup')
  self.assertEqual(report['status'],'conflicts');self.assertIn('ADWS',unrelated.read_text())
 def test_invalid_color_cannot_inject_terminal_controls(self):
  self.colors['primary']='\x1b]52;malicious'
  with self.assertRaises(ValueError):palette.foot_sequences(self.colors)
 def test_reload_failure_is_reported_not_swallowed(self):
  reg=self.install(['mako']);runner=Mock(side_effect=OSError('IPC unavailable'))
  result=palette.synchronize(self.colors,reg,runner=runner,process_finder=lambda _:[(22,['mako'])],signaler=Mock())
  self.assertEqual(result['status'],'partial');self.assertEqual(result['targets']['mako']['status'],'failed')
  report=json.loads((self.root/'state/adws/palette-last-result.json').read_text());self.assertEqual(report['status'],'partial')

if __name__=='__main__':unittest.main()
