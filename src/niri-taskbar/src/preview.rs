//! One cancellable capture helper per visible popup. No GTK-thread blocking I/O.
use std::{collections::HashMap,ffi::OsStr};
use waybar_cffi::gtk::{self,gio,glib,prelude::*};

pub fn start(helper:&str, images:Vec<(u64,gtk::Image,gtk::Label)>, popup:&gtk::Popover)->Option<gio::Subprocess> {
    let unavailable=crate::i18n::text("预览暂不可用","Preview unavailable");
    for (_,_,status) in &images{status.set_text(unavailable);}
    if helper.is_empty() || images.is_empty(){return None;}
    let mut args=vec!["python3".to_string(),helper.to_string()];
    args.extend(images.iter().map(|(id,_,_)|id.to_string()));
    let args:Vec<&OsStr>=args.iter().map(OsStr::new).collect();
    let process=gio::Subprocess::newv(&args,gio::SubprocessFlags::STDOUT_PIPE|gio::SubprocessFlags::STDERR_SILENCE).ok()?;
    for (_,_,status) in &images{status.set_text(crate::i18n::text("正在加载预览…","Loading preview…"));}
    let input=gio::DataInputStream::new(&process.stdout_pipe()?);
    let images:HashMap<_,_>=images.into_iter().map(|(id,image,status)|(id,(image.downgrade(),status.downgrade()))).collect();
    let weak=popup.downgrade();
    glib::MainContext::default().spawn_local(async move {
        while let Ok(line)=input.read_line_future(glib::Priority::DEFAULT).await {
            if line.is_empty(){break;}
            if !weak.upgrade().is_some_and(|p|p.is_visible()){break;}
            if line.len()>512*1024{continue;}
            let Ok(value)=serde_json::from_slice::<serde_json::Value>(&line) else{continue};
            let Some(id)=value["id"].as_u64() else{continue};
            let Some(encoded)=value["png"].as_str() else{continue};
            let Some(image)=images.get(&id).and_then(|(w,_)|w.upgrade()) else{continue};
            let bytes=glib::base64_decode(encoded);
            let loader=gtk::gdk_pixbuf::PixbufLoader::new();
            if loader.write(&bytes).is_ok() && loader.close().is_ok(){
                if let Some(pixbuf)=loader.pixbuf(){image.set_from_pixbuf(Some(&pixbuf));if let Some(status)=images.get(&id).and_then(|(_,w)|w.upgrade()){status.set_opacity(0.);}}
            }
        }
        for (_,(_,status)) in images{if let Some(status)=status.upgrade(){status.set_text(unavailable);}}
    });
    Some(process)
}
