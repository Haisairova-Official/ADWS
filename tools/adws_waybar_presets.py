"""Independent ADWS Waybar layouts, staged until the user applies them."""
import json
from pathlib import Path

PRESETS=(('standard','标准','保留当前的箭头分区与展开组件。'),
         ('simple','简洁','紧凑的圆角栏，只保留常用组件。'),
         ('status','状态','仅显示处理器、内存、网络、声音等系统状态。'),
         ('gnome','Gnome 风格','新版 GNOME：左侧工作区指示器，中间日期时间，右侧合并状态菜单。'))


def rendered(key='standard',root=None,preview=False):
    if key not in {item[0] for item in PRESETS}:raise ValueError('Unknown Waybar preset')
    import adws_topbar
    root=root or adws_topbar.ROOT
    text,css=adws_topbar.rendered(root,preview=preview)
    data=json.loads(text)
    if key=='standard':
        data['adws-preset']='standard'
        return json.dumps(data,ensure_ascii=False,indent=2)+'\n',css
    audio='pulseaudio' if data['group/audio']['modules'][0]=='pulseaudio' else 'wireplumber'
    workspaces='hyprland/workspaces' if 'hyprland/workspaces' in data['modules-left'] else 'niri/workspaces'
    window='hyprland/window' if workspaces.startswith('hyprland') else 'niri/window'
    common=[audio,'network','bluetooth']
    if 'battery' in data['modules-right']:common.append('battery')
    if key=='simple':
        data.update({'modules-left':['custom/applauncher',workspaces,window], 'modules-center':['clock'],
                     'modules-right':['custom/clipboard',*common,'tray','custom/wlogout']})
    elif key=='status':
        data.update({'modules-left':['cpu','memory'],'modules-center':[],
                     'modules-right':[*common,'tray','clock']})
    else:
        import shlex,sys
        from adws_i18n import chinese,tr
        def popup(kind):return shlex.join([sys.executable,str(root/'tools/adws_gnome_menu.py'),kind,*(['--preview'] if preview else [])])
        overview='niri msg action toggle-overview' if workspaces=='niri/workspaces' else data['custom/applauncher']['on-click']
        data[workspaces].update({'format':'','disable-click':True,'all-outputs':False,'tooltip':False})
        data['group/gnome-overview']={'orientation':'horizontal','modules':[workspaces],'on-click':overview,'on-click-right':overview}
        status=['network',audio]
        if 'battery' in common:status.append('battery')
        data['group/gnome-system']={'orientation':'horizontal','modules':status,'on-click':popup('system')}
        for module in status:
            data[module]['on-click']=popup('system');data[module]['on-click-right']=popup('system')
        data[audio]['format']='{icon}' if audio=='pulseaudio' else ''
        data[audio]['format-muted']=''
        data['battery'].update({'format':'{icon}','format-charging':'󰂄','format-icons':['','','','','']})
        data.update({'modules-left':['group/gnome-overview'],'modules-center':['clock'],'modules-right':['group/gnome-system'], 'height':30,'margin-top':48 if preview else 0,'margin-bottom':0,'margin-left':0,'margin-right':0})
        data['clock']['format']='{:%m月%d日 %a  %H:%M}' if chinese() else '{:%a %b %e  %H:%M}'
        data['clock']['on-click']=popup('calendar')
    if preview:data['modules-right'].append('custom/adws-preview-close')
    data['name']='adws-top-preview' if preview else 'adws-top-'+key
    data['adws-preset']=key
    css='''/* ADWS independently authored compact Waybar presets. */
@import "colors.css";
* { border: none; min-height: 0; }
window#waybar { background: transparent; color: @on_surface; border-radius: 0; box-shadow: none; }
window#waybar decoration { background: transparent; border: none; box-shadow: none; }
window#waybar > box { background: @surface_container_high; border: 1px solid alpha(@on_surface,.12); border-radius: 12px; }
label.module, #tray { padding: 5px 10px; font-family: "JetBrainsMono Nerd Font Propo"; font-size: 16.6px; }
#window, #clock, tooltip label { font-family: inherit; font-size: inherit; }
#window { color: @on_surface_variant; }
#workspaces button { font-family: "JetBrainsMono Nerd Font Propo"; font-size: 16.6px; background: transparent; color: @on_surface_variant; padding: 0 8px; border-radius: 8px; box-shadow: none; }
#workspaces button.active { color: @primary; background: alpha(@primary,.12); }
#workspaces button:hover { background: alpha(@on_surface,.1); }
#custom-applauncher { color: @primary; }
#custom-wlogout { color: @error; }
#cpu, #memory { color: @tertiary; }
tooltip { background: @surface_container_high; color: @on_surface; border-radius: 10px; border: 1px solid @outline_variant; }
tooltip label { padding: 8px; }
'''
    if key=='simple':data['spacing']=2
    if key=='status':
        data['cpu']['format']=' {usage}%';data['memory']['format']=' {percentage}%'
    if key=='gnome':
        data['spacing']=0
        css="""/* ADWS GNOME-style top bar: independently authored. */
@import "colors.css";
* { min-height: 0; border: none; box-shadow: none; }
window#waybar decoration { background: transparent; border: none; box-shadow: none; }
window#waybar, window#waybar > box { background: #000000; color: #f6f5f4; border: none; border-radius: 0; padding: 0; margin: 0; }
label.module { padding: 0 7px; color: #f6f5f4; }
#clock { font-weight: bold; border-radius: 99px; padding: 0 14px; margin: 3px 0; }
#clock:hover, #gnome-system:hover, #gnome-overview:hover { background: #303030; }
#gnome-system, #gnome-overview { border-radius: 99px; margin: 3px 6px; padding: 0 8px; }
#network, #pulseaudio, #wireplumber, #battery { font-family: "JetBrainsMono Nerd Font Propo"; font-size: 14px; color: #f6f5f4; }
#workspaces { background: transparent; padding: 0 3px; }
#workspaces button { min-width: 7px; min-height: 7px; padding: 0; margin: 9px 4px; background: #8e8e8e; color: transparent; border-radius: 99px; }
#workspaces button label { font-size: 0; padding: 0; margin: 0; }
#workspaces button.active, #workspaces button.focused { min-width: 25px; background: #f6f5f4; }
#workspaces button:hover { background: #f6f5f4; }
tooltip { background: #303030; color: #f6f5f4; border: 1px solid #454545; border-radius: 12px; }
tooltip label { padding: 8px; }
"""
    return json.dumps(data,ensure_ascii=False,indent=2)+'\n',css
