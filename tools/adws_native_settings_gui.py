"""ADWS-owned service settings, with bounded discovery outside GTK."""
import copy
import os
from pathlib import Path
import threading
from gi.repository import Gdk, GLib, Gtk
from adws_i18n import tr
import adws_native_services as backend


def caption(value, css=None):
    widget=Gtk.Label(label=tr(value),xalign=0)
    widget.set_line_wrap(True)
    if css: widget.get_style_context().add_class(css)
    return widget


def choice(values, active=None):
    widget=Gtk.ComboBoxText()
    for key,title in values: widget.append(str(key),tr(title))
    if active is not None: widget.set_active_id(str(active))
    elif values: widget.set_active(0)
    return widget


def entry(value='',secret=False):
    widget=Gtk.Entry(text=str(value))
    widget.set_visibility(not secret)
    widget.set_max_length(1024 if secret else 2048)
    return widget


def button(title,callback):
    widget=Gtk.Button(label=tr(title))
    widget.connect('clicked',lambda *_:callback())
    return widget


def row(box,title,control,detail=None,leading=None):
    line=Gtk.Box(spacing=16)
    if leading is not None:
        leading.set_valign(Gtk.Align.CENTER)
        line.pack_start(leading,False,False,0)
    labels=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
    labels.pack_start(caption(title),False,False,0)
    if detail: labels.pack_start(caption(detail,'dim-label'),False,False,0)
    line.pack_start(labels,True,True,0)
    control.set_valign(Gtk.Align.CENTER)
    line.pack_end(control,False,False,0)
    box.pack_start(line,False,False,0)
    return line


class Form(Gtk.Dialog):
    def __init__(self,host,title):
        super().__init__(title=tr(title),transient_for=host,modal=True,use_header_bar=True,destroy_with_parent=True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.get_style_context().add_class('adws-system-settings')
        self.set_default_size(640,560)
        self.add_button(tr('取消'),Gtk.ResponseType.CANCEL)
        self.add_button(tr('应用更改'),Gtk.ResponseType.OK)
        self.fields={}
        scroll=Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)
        self.body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        self.body.set_border_width(24)
        scroll.add(self.body)
        self.get_content_area().pack_start(scroll,True,True,0)

    def field(self,key,title,widget):
        self.fields[key]=widget
        row(self.body,title,widget)
        return widget

    def values(self):
        result={}
        for key,widget in self.fields.items():
            if isinstance(widget,Gtk.SpinButton): result[key]=widget.get_value_as_int()
            elif isinstance(widget,Gtk.Entry): result[key]=widget.get_text()
            elif isinstance(widget,Gtk.ComboBoxText): result[key]=widget.get_active_id()
            elif isinstance(widget,Gtk.Switch): result[key]=widget.get_active()
            elif isinstance(widget,Gtk.FileChooserButton): result[key]=widget.get_filename() or ''
        return result

    def read(self):
        from adws_settings_widgets import enhance_choices
        self.show_all();enhance_choices(self.body,translate=tr)
        try: return self.values() if self.run()==Gtk.ResponseType.OK else None
        finally: self.destroy()


class NativeSection:
    def __init__(self,host,parent,title,loader,render,service=None):
        self.host,self.loader,self.render,self.service=host,loader,render,service
        self.closed,self.generation,self.loading=False,0,False
        self.box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        self.box.get_style_context().add_class('settings-card')
        toolbar=Gtk.Box(spacing=12)
        toolbar.pack_start(caption(title,'settings-section-title'),True,True,0)
        self.refresh_button=button('刷新状态',self.refresh)
        toolbar.pack_end(self.refresh_button,False,False,0)
        self.box.pack_start(toolbar,False,False,0)
        self.content=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        self.box.pack_start(self.content,False,False,0)
        self.box.connect('destroy',self.destroy)
        parent.pack_start(self.box,False,False,0)
        self.refresh()

    def destroy(self,*_): self.closed=True;self.generation+=1

    def refresh(self):
        if self.closed or self.loading:return
        self.loading=True;self.refresh_button.set_sensitive(False)
        self.generation+=1;generation=self.generation
        for widget in self.content.get_children():widget.destroy()
        self.content.pack_start(caption('正在读取系统状态…','dim-label'),False,False,0)
        self.content.show_all()
        def load():
            try:data,error=self.loader(),None
            except Exception as exc:data,error=None,str(exc)
            GLib.idle_add(done,data,error)
        def done(data,error):
            if self.closed or self.host.closed or generation!=self.generation:return False
            self.loading=False;self.refresh_button.set_sensitive(True)
            for widget in self.content.get_children():widget.destroy()
            if error:
                self.content.pack_start(caption(error,'dim-label'),False,False,0)
                if self.service:self.content.pack_start(button('安装所需系统服务',self.install),False,False,0)
            else:
                try:self.render(self,data)
                except Exception as exc:self.content.pack_start(caption(str(exc),'dim-label'),False,False,0)
            from adws_settings_widgets import enhance_choices
            self.content.show_all();enhance_choices(self.content,translate=tr)
            return False
        threading.Thread(target=load,daemon=True).start()

    def install(self):
        if self.host.confirm('安装所需系统服务？','将安装后台服务，不安装 GNOME 或 KDE 控制中心。'):
            self.change(lambda:backend.install_service(self.service))

    def change(self,job,after=None):
        if self.host.busy or self.closed:
            self.refresh();return
        def completed():
            if after:after()
            self.refresh()
        self.host.run_worker(job,completed,on_failure=self.refresh)


def wifi_form(host,ap=None):
    dialog=Form(host,'连接 Wi-Fi')
    dialog.field('ssid','网络名称',entry(ap['name'] if ap else ''))
    security=ap['security'] if ap else 'wpa-psk'
    dialog.field('security','安全方式',choice([('open','开放网络'),('wpa-psk','WPA/WPA2 Personal'),('sae','WPA3 Personal'),('enterprise','WPA Enterprise'),('wep','WEP')],security))
    dialog.field('password','密码',entry(secret=True))
    dialog.field('identity','企业网络用户名',entry())
    dialog.field('eap','企业网络认证方式',choice([('peap','PEAP'),('ttls','TTLS'),('tls','TLS')]))
    dialog.field('ca','企业网络 CA 证书',Gtk.FileChooserButton.new(tr('选择文件'),Gtk.FileChooserAction.OPEN))
    dialog.field('client','TLS 客户端证书',Gtk.FileChooserButton.new(tr('选择文件'),Gtk.FileChooserAction.OPEN))
    dialog.field('private','TLS 私钥文件',Gtk.FileChooserButton.new(tr('选择文件'),Gtk.FileChooserAction.OPEN))
    dialog.field('key_password','TLS 私钥密码',entry(secret=True))
    dialog.body.pack_start(caption('企业网络须选择 CA 证书，避免连接到伪造的认证服务器。','dim-label'),False,False,0)
    values=dialog.read()
    if not values:return None
    ssid=ap['ssid'] if ap and values['ssid']==ap['name'] else values['ssid']
    return backend.wifi_settings(values['ssid'],ssid,values['security'],values['password'],values['identity'],values['ca'],values['eap'],values['client'],values['private'],values['key_password'])


def network_sections(host,parent):
    def nearby(section,data):
        profiles=data['profiles'];data=data['aps']
        section.content.pack_start(button('扫描附近网络',lambda:section.change(lambda:backend.nm_wifi(scan=True))),False,False,0)
        section.content.pack_start(button('连接隐藏网络…',lambda:connect(section,None)),False,False,0)
        for ap in data:
            security={'enterprise':'wpa-eap','wep':'none','open':'open'}.get(ap['security'],ap['security'])
            saved=[]
            for profile in profiles:
                wireless=profile['settings'].get('802-11-wireless',{})
                ssid=wireless.get('ssid');key=profile['settings'].get('802-11-wireless-security',{}).get('key-mgmt')
                if ssid is not None and bytes(ssid.unpack())==ap['ssid'] and (key.unpack() if key else 'open')==security:saved.append(profile)
            control=button('已连接' if ap['active'] else '连接',lambda ap=ap,p=(saved[0] if saved else None):section.change(lambda:backend.nm_activate(p,True)) if p else connect(section,ap))
            control.set_sensitive(not ap['active'])
            row(section.content,ap['name'],control,f"{ap['signal']}% · {ap['security']}")
        if not data:section.content.pack_start(caption('没有发现附近网络。','dim-label'),False,False,0)
    def connect(section,ap):
        try:settings=wifi_form(host,ap)
        except Exception as error:host.error(str(error));return
        if settings:
            if ap is None:settings['802-11-wireless']['hidden']=GLib.Variant('b',True)
            section.change(lambda:backend.nm_create(settings,ap['device'] if ap else '/',ap['path'] if ap else '/'))
    def available():return {'aps':backend.nm_wifi(),'profiles':backend.nm_profiles()}
    NativeSection(host,parent,'附近 Wi-Fi 与隐藏网络',available,nearby,'network')
    def profiles(section,data):
        actions=Gtk.Box(spacing=10)
        actions.pack_start(button('添加有线连接',lambda:add_ethernet(section)),False,False,0)
        actions.pack_start(button('导入 VPN…',lambda:import_vpn(section)),False,False,0)
        section.content.pack_start(actions,False,False,0)
        for profile in data:
            controls=Gtk.Box(spacing=8)
            controls.pack_start(button('断开' if profile.get('active') else '连接',lambda p=profile:toggle_profile(section,p)),False,False,0)
            controls.pack_start(button('编辑',lambda p=profile:edit_profile(section,p)),False,False,0)
            controls.pack_start(button('删除',lambda p=profile:delete_profile(section,p)),False,False,0)
            row(section.content,profile['name'],controls,profile['type'])
    NativeSection(host,parent,'网络配置、地址与 VPN',backend.nm_profiles,profiles,'network')


def toggle_profile(section,profile):
    enabled=not bool(profile.get('active'))
    if not enabled and not section.host.confirm('断开此网络连接？',profile['name']):return
    section.change(lambda:backend.nm_activate(profile,enabled))


def add_ethernet(section):
    dialog=Form(section.host,'添加有线连接')
    dialog.field('name','连接名称',entry('Ethernet'))
    dialog.field('device','设备名称（可留空）',entry())
    values=dialog.read()
    if not values:return
    try:
        name=backend.text(values['name']);device=values['device'].strip()
        if device:backend.text(device,64)
        import uuid,pwd
        settings={'connection':{'id':GLib.Variant('s',name),'uuid':GLib.Variant('s',str(uuid.uuid4())),
                  'type':GLib.Variant('s','802-3-ethernet'),'permissions':GLib.Variant('as',['user:'+pwd.getpwuid(os.getuid()).pw_name+':'])},
                  '802-3-ethernet':{},'ipv4':backend.ip_settings(4,'auto'),'ipv6':backend.ip_settings(6,'auto')}
        if device:settings['connection']['interface-name']=GLib.Variant('s',device)
    except Exception as error:section.host.error(str(error));return
    section.change(lambda:backend.nm_create(settings,activate=False))


def delete_profile(section,profile):
    if section.host.confirm('删除网络配置？',profile['name']+'\n'+tr('已连接的网络可能会断开。')):
        section.change(lambda:backend.nm_delete(profile['path']))


def edit_profile(section,profile):
    dialog=Form(section.host,'编辑网络配置')
    settings=profile['settings']
    def value(group,name,default=''):
        item=settings.get(group,{}).get(name)
        return item.unpack() if item is not None else default
    dialog.field('name','连接名称',entry(profile['name']))
    auto=Gtk.Switch(active=value('connection','autoconnect',True))
    dialog.field('auto','自动连接',auto)
    for version in (4,6):
        group='ipv'+str(version)
        dialog.body.pack_start(caption('IPv'+str(version),'settings-section-title'),False,False,0)
        dialog.field(group+'.method','地址分配方式',choice([('auto','自动（DHCP）'),('manual','手动'),('disabled','禁用'),('link-local','仅本地链路')],value(group,'method','auto')))
        addresses=value(group,'address-data',[])
        dialog.field(group+'.addresses','IP 地址 / 前缀',entry(', '.join(f"{a['address']}/{a['prefix']}" for a in addresses)))
        dialog.field(group+'.gateway','网关',entry(value(group,'gateway')))
        dns=value(group,'dns-data',[])
        if not dns:
            legacy=value(group,'dns',[])
            import ipaddress
            dns=[str(ipaddress.IPv4Address(int.from_bytes(int(a).to_bytes(4,'little'),'big'))) if version==4 else str(ipaddress.IPv6Address(bytes(a))) for a in legacy]
        dialog.field(group+'.dns','DNS 地址',entry(', '.join(dns)))
    dialog.field('proxy.method','代理方式',choice([('0','无代理'),('1','自动代理（PAC）')],value('proxy','method',0)))
    dialog.field('proxy.url','PAC 地址',entry(value('proxy','pac-url')))
    vpn=settings.get('vpn',{}).get('data')
    vpn_keys=[]
    if '802-11-wireless-security' in settings:
        dialog.field('wifi.password','新密码（留空则保留）',entry(secret=True))
    if vpn is not None:
        dialog.field('vpn.password','VPN 新密码（留空则保留）',entry(secret=True))
        dialog.field('vpn.username','VPN 用户名',entry(value('vpn','user-name')))
    if vpn is not None:
        dialog.body.pack_start(caption('VPN 参数','settings-section-title'),False,False,0)
        for key,item in vpn.unpack().items():
            vpn_keys.append(key);dialog.field('vpn.'+key,key,entry(item))
    dialog.body.pack_start(caption('保存配置后，重新连接此网络才会应用地址变化。','dim-label'),False,False,0)
    data=dialog.read()
    if not data:return
    try:
        updates={'connection':{'id':GLib.Variant('s',backend.text(data['name'])),'autoconnect':GLib.Variant('b',data['auto'])}}
        for version in (4,6):
            group='ipv'+str(version)
            updates[group]=backend.ip_settings(version,data[group+'.method'],data[group+'.addresses'],data[group+'.gateway'],data[group+'.dns'])
            # Empty fields must clear an old address/gateway instead of silently
            # keeping it after the user switched to DHCP or erased the entry.
            updates[group].setdefault('address-data',GLib.Variant('aa{sv}',[]))
            updates[group].setdefault('gateway',GLib.Variant('s',''))
        updates['proxy']={'method':GLib.Variant('i',int(data['proxy.method'])),'pac-url':GLib.Variant('s',data['proxy.url'])}
        if vpn_keys:updates['vpn']={'data':GLib.Variant('a{ss}',{key:data['vpn.'+key] for key in vpn_keys})}
        if vpn is not None:
            updates.setdefault('vpn',{})['user-name']=GLib.Variant('s',data['vpn.username'])
            if data['vpn.password']:updates['vpn']['secrets']=GLib.Variant('a{ss}',{'password':data['vpn.password']});vpn_data=value('vpn','data',{});vpn_data.update({key:data['vpn.'+key] for key in vpn_keys});vpn_data['password-flags']='0';updates['vpn']['data']=GLib.Variant('a{ss}',vpn_data)
        if data.get('wifi.password'):
            key=value('802-11-wireless-security','key-mgmt')
            secret='psk' if key in ('wpa-psk','sae') else 'wep-key0' if key=='none' else None
            if secret:
                verified=backend.wifi_settings(profile['name'],value('802-11-wireless','ssid'), 'wep' if key=='none' else key,data['wifi.password'])
                updates['802-11-wireless-security']={secret:verified['802-11-wireless-security'][secret],('psk-flags' if secret=='psk' else 'wep-key-flags'):GLib.Variant('u',0)}
            else:updates['802-1x']={'password':GLib.Variant('s',data['wifi.password']),'password-flags':GLib.Variant('u',0)}
    except Exception as error:section.host.error(str(error));return
    section.change(lambda:backend.nm_update(profile,updates))


def import_vpn(section):
    dialog=Form(section.host,'导入 VPN')
    dialog.field('provider','VPN 类型',choice([('wireguard','WireGuard'),('openvpn','OpenVPN'),('openconnect','OpenConnect'),('vpnc','Cisco VPN')]))
    chooser=Gtk.FileChooserButton.new(tr('选择 VPN 配置文件'),Gtk.FileChooserAction.OPEN)
    row(dialog.body,'配置文件',chooser)
    def install_provider():
        provider=dialog.fields['provider'].get_active_id()
        if provider=='wireguard':return
        if section.host.confirm('安装 VPN 后台插件？',provider):
            section.change(lambda:backend.install_service('vpn-'+provider))
    dialog.body.pack_start(button('安装所选 VPN 后台插件',install_provider),False,False,0)
    dialog.show_all()
    from adws_settings_widgets import enhance_choices
    enhance_choices(dialog.body,translate=tr)
    accepted=dialog.run()==Gtk.ResponseType.OK
    provider=dialog.fields['provider'].get_active_id();filename=chooser.get_filename();dialog.destroy()
    if accepted and filename:section.change(lambda:backend.vpn_import(provider,filename))


def sound_sections(host,parent):
    from adws_sound_settings import sound_sections as build_sound
    return build_sound(host,parent)


def bluetooth_sections(host,parent):
    from adws_native_bluetooth import snapshot,action,PairingAgent
    state={'adapter':None,'scanning':False,'agent':None}
    def stop():
        if state['agent']:state['agent'].close();state['agent']=None
        if state['scanning'] and state['adapter']:
            adapter=state['adapter'];state['scanning']=False
            def finish():
                try:action(adapter,None,'StopDiscovery')
                except Exception:pass
            threading.Thread(target=finish,daemon=True).start()
    def render(section,data):
        adapter=data['adapter']
        if not adapter:section.content.pack_start(caption('未检测到蓝牙适配器。'),False,False,0);return
        state['adapter']=adapter['path']
        if len(data['adapters'])>1:
            selector=choice([(item['path'],item.get('Alias',item['path'])) for item in data['adapters']],adapter['path'])
            def select(control):
                selected=control.get_active_id();stop();state['adapter']=selected;section.refresh()
            selector.connect('changed',select);row(section.content,'蓝牙适配器',selector)
            radio=Gtk.Switch(active=adapter.get('Powered',False))
            def set_radio(control,_):
                value=control.get_active()
                if not value and not host.confirm('关闭蓝牙？','已连接的蓝牙键盘、鼠标和耳机将会断开。'):
                    section.refresh();return
                section.change(lambda:action(adapter['path'],None,'Powered',value))
            radio.connect('notify::active',set_radio);row(section.content,'所选适配器电源',radio)
        section.content.pack_start(button('停止搜索' if state['scanning'] else '搜索附近设备',lambda:scan(section)),False,False,0)
        for device in data['devices']:
            controls=Gtk.Box(spacing=8)
            path=device['path']
            if not device.get('Paired'):
                controls.pack_start(button('配对',lambda d=device:pair(section,d,data['owner'])),False,False,0)
            else:
                controls.pack_start(button('断开' if device.get('Connected') else '连接',lambda d=device:section.change(lambda:action(state['adapter'],d['path'],'Disconnect' if d.get('Connected') else 'Connect'))),False,False,0)
                controls.pack_start(button('移除',lambda d=device:remove(section,d)),False,False,0)
                trust=Gtk.Switch(active=device.get('Trusted',False))
                trust.connect('notify::active',lambda control,_,p=path:trust_device(section,p,control.get_active()))
                controls.pack_start(trust,False,False,0);trust.set_tooltip_text(tr('信任此设备以允许自动重连'))
            row(section.content,device.get('Alias') or device.get('Name') or device['Address'],controls,device['Address'])
    def trust_device(section,path,value):section.change(lambda:action(state['adapter'],path,'Trusted',value))
    def scan(section):
        desired=not state['scanning'];adapter=state['adapter']
        def scanned():
            state['scanning']=desired
            if not desired:return
            for delay in (2,5,8):
                GLib.timeout_add_seconds(delay,lambda:(section.refresh() if not section.closed and state['scanning'] else None,False)[1])
            GLib.timeout_add_seconds(12,lambda:(stop(),section.refresh() if not section.closed else None,False)[2])
        section.change(lambda:action(adapter,None,'StartDiscovery' if desired else 'StopDiscovery'),after=scanned)
    def pair(section,device,owner):
        if state['agent'] or host.busy:return
        if not host.confirm('配对此设备？',device.get('Alias',device['Address'])):return
        def complete(error):
            state['agent']=None
            if error and not section.closed:host.error(error)
            section.refresh()
        try:state['agent']=PairingAgent(host,device['path'],owner,complete)
        except Exception as error:host.error(str(error))
    def remove(section,device):
        if host.confirm('移除已配对设备？',device.get('Alias',device['Address'])):
            section.change(lambda:action(state['adapter'],device['path'],'RemoveDevice'))
    section=NativeSection(host,parent,'设备搜索、配对与信任',lambda:snapshot(state['adapter']),render,'bluetooth')
    section.box.connect('destroy',lambda *_:stop())


def account_sections(host,parent):
    from adws_native_accounts import users,user_change,edit_user,create_user,timezone_snapshot,set_timezone,set_ntp,locale_snapshot,set_locales,set_time
    def refresh_header():
        header=getattr(host,'account_header',None)
        if header:header.refresh(force=True)
    def render(section,data):
        section.content.pack_start(button('添加账户…',lambda:create(section)),False,False,0)
        for account in data:
            controls=Gtk.Box(spacing=8)
            controls.pack_start(button('编辑',lambda a=account:edit(section,a)),False,False,0)
            if account['Uid']>=1000 and account['Uid']!=os.getuid():
                controls.pack_start(button('删除',lambda a=account:remove(section,a)),False,False,0)
            from adws_account_header import account_role, ROLE_LABELS, avatar_image
            avatar=avatar_image(account.get('avatar_png'))
            role=tr(ROLE_LABELS[account_role(account['Uid'],account.get('AccountType'))])
            row(section.content,account.get('RealName') or account['UserName'],controls,
                account['UserName']+' · '+role,leading=avatar)
    def create(section):
        form=Form(host,'添加账户')
        form.field('username','用户名',entry());form.field('name','显示名称',entry())
        form.field('admin','账户类型',choice([('0','标准账户'),('1','管理员')]))
        form.field('password','密码',entry(secret=True));form.field('repeat','确认密码',entry(secret=True))
        values=form.read()
        if not values:return
        if values['password']!=values['repeat']:host.error(tr('两次输入的密码不一致。'));return
        section.change(lambda:create_user(values['username'],values['name'],values['admin']=='1',values['password']))
    def edit(section,account):
        form=Form(host,'编辑账户')
        form.field('name','显示名称',entry(account.get('RealName','')))
        role=form.field('admin','账户类型',choice([('0','标准账户'),('1','管理员')],account.get('AccountType',0)))
        role.set_sensitive(account['Uid']>=1000 and account['Uid']!=os.getuid())
        locked=form.field('locked','禁用此账户',Gtk.Switch(active=account.get('Locked',False)))
        locked.set_sensitive(account['Uid']>=1000 and account['Uid']!=os.getuid())
        form.field('password','新密码（留空则保留）',entry(secret=True));form.field('repeat','确认密码',entry(secret=True))
        image=Gtk.FileChooserButton.new(tr('选择头像'),Gtk.FileChooserAction.OPEN);row(form.body,'头像',image)
        avatar=[None]
        image.connect('file-set',lambda *_:avatar.__setitem__(0,image.get_filename()))
        values=form.read()
        if not values:return
        if values['password']!=values['repeat']:host.error(tr('两次输入的密码不一致。'));return
        changes={}
        for field,old,new in [('name',account.get('RealName',''),values['name']),('type',bool(account.get('AccountType',0)),values['admin']=='1'),('locked',account.get('Locked',False),values['locked'])]:
            if old!=new:changes[field]=new
        if avatar[0]:changes['avatar']=avatar[0]
        if values['password']:changes['password']=values['password']
        section.change(lambda:edit_user(account,changes),after=refresh_header)
    def remove(section,account):
        form=Form(host,'删除账户')
        form.body.pack_start(caption(account['UserName']),False,False,0)
        form.field('files','同时删除此账户的主目录',Gtk.Switch(active=False))
        values=form.read()
        if values is not None and host.confirm('删除账户？',tr('此操作无法撤销。')):section.change(lambda:user_change(account,'delete',values['files']))
    NativeSection(host,parent,'账户管理',users,render,'region')
    def clock(section,data):
        zone=choice([(value,value) for value in data['zones']],data['timezone'])
        row(section.content,'时区',zone)
        section.content.pack_start(button('应用时区',lambda:section.change(lambda value=zone.get_active_id():set_timezone(value))),False,False,0)
        ntp=Gtk.Switch(active=data['ntp']);ntp.set_sensitive(data['can_ntp'])
        ntp.connect('notify::active',lambda control,_:section.change(lambda value=control.get_active():set_ntp(value)))
        row(section.content,'自动同步系统时间',ntp)
        def manual():
            form=Form(host,'手动设置系统时间')
            from datetime import datetime
            form.field('time','日期时间（含时区）',entry(datetime.now().astimezone().isoformat(timespec='seconds')))
            values=form.read()
            if values and host.confirm('修改系统时间？',values['time']):section.change(lambda:set_time(values['time']))
        control=button('手动设置系统时间…',manual);control.set_sensitive(not data['ntp'])
        section.content.pack_start(control,False,False,0)
    NativeSection(host,parent,'日期、时间与时区',timezone_snapshot,clock)
    def locale(section,data):
        from adws_system_pages import locale_key,locale_title
        controls={}
        for key,title in [('LANG','默认界面语言'),('LC_TIME','日期与时间格式'),('LC_NUMERIC','数字格式')]:
            active=data['values'].get(key,data['values'].get('LANG','C.UTF-8'))
            selected=next((v for v in data['locales'] if locale_key(v)==locale_key(active)),None)
            control=choice([(v,locale_title(v)) for v in data['locales']],selected)
            controls[key]=control;row(section.content,title,control)
        section.content.pack_start(caption('这是系统默认地区设置，需要管理员授权，重新登录后生效。个人账户语言优先于系统默认值。','dim-label'),False,False,0)
        def apply():
            changes={key:control.get_active_id() for key,control in controls.items()}
            if host.confirm('修改系统默认语言与地区？','此修改会影响使用系统默认语言的所有账户。'):
                section.change(lambda:set_locales(data,changes))
        section.content.pack_start(button('应用地区设置',apply),False,False,0)
    NativeSection(host,parent,'系统默认语言与地区',locale_snapshot,locale)


def power_sections(host,parent):
    import adws_power_policy as policy
    def render(section,data):
        enabled=Gtk.Switch(active=data['enabled']);row(section.content,'启用 ADWS 空闲电源策略',enabled)
        controls={}
        for source,title in [('ac','接通电源时'),('battery','使用电池时')]:
            section.content.pack_start(caption(title,'settings-section-title'),False,False,0)
            controls[source]={}
            for field,label in [('screen','关闭显示器（分钟）'),('suspend','自动睡眠（分钟）')]:
                value=Gtk.SpinButton.new_with_range(0,240,1);value.set_value(data[source][field])
                controls[source][field]=value;row(section.content,label,value)
        section.content.pack_start(caption('0 表示从不。仅管理当前 Wayland 会话；不会修改其他桌面环境的策略。','dim-label'),False,False,0)
        def apply():
            values={'enabled':enabled.get_active(),**{source:{field:control.get_value_as_int() for field,control in items.items()} for source,items in controls.items()}}
            section.change(lambda:policy.save(values))
        section.content.pack_start(button('应用电源策略',apply),False,False,0)
        import shutil
        if not shutil.which('swayidle'):
            section.content.pack_start(caption('需要 swayidle 获取 Wayland 空闲事件；无需安装其他桌面的电源设置程序。','dim-label'),False,False,0)
            section.content.pack_start(button('安装所需系统服务',section.install),False,False,0)
    NativeSection(host,parent,'屏幕关闭与自动睡眠',policy.load,render,'power')

    def hardware(section,data):
        options=[('ignore','不执行动作'),('poweroff','关机'),('suspend','睡眠'),('hibernate','休眠'),('lock','锁定')]
        fields={}
        for key,title in [('HandlePowerKey','电源按钮'),('HandleLidSwitch','合上笔记本盖子'),('HandleLidSwitchExternalPower','接通电源时合盖'),('HandleLidSwitchDocked','连接外部显示器时合盖')]:
            values=options if data[key] in {v[0] for v in options} else [*options,(data[key],data[key])]
            fields[key]=choice(values,data[key]);row(section.content,title,fields[key])
        section.content.pack_start(caption('此策略是系统级设置，需要管理员授权，重启系统后生效。','dim-label'),False,False,0)
        def apply():
            values={key:control.get_active_id() for key,control in fields.items()}
            if host.confirm('保存系统电源按钮与合盖策略？','此策略是系统级设置，需要管理员授权，重启系统后生效。'):
                section.change(lambda:policy.logind_save(values))
        section.content.pack_start(button('应用更改',apply),False,False,0)
    NativeSection(host,parent,'电源按钮与笔记本合盖',policy.logind_snapshot,hardware)
