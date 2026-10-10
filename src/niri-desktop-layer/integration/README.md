# 底栏淡出和占位时序

`waybar-space.c` 是 Waybar CFFI v2 模块，不创建进程或显示额外按钮。
底栏 `modes.invisible` 的 `visible` 和 `exclusive` 都应为 `true`，
`passthrough` 为 `true`。CSS 对 `window#waybar > box` 做 220ms 透明度过渡。
模块监听该容器的样式变化，在进入 invisible 后等待 240ms 再将保留空间设为零。
退出 invisible 时取消计时，Waybar 默认模式自动恢复保留空间。

这里调整的是释放位置的时机，不是 Niri 本身的窗口缩放动画。
原本启用的窗口动画和规则保持不变。

编译需要 GTK3 和 gtk-layer-shell 的开发文件。从项目根目录执行：

```sh
cc -shared -fPIC -O2 -Wall -Wextra -Werror integration/waybar-space.c \
  -o integration/libwaybar-space.new.so \
  $(pkg-config --cflags --libs gtk+-3.0 gtk-layer-shell-0 wayland-client) -lm
mv integration/libwaybar-space.new.so integration/libwaybar-space.so
```

已加载的库应通过上述临时文件原子替换，不能直接截断覆盖；然后仅重新加载底栏进程。
配置中的库路径为项目绝对路径，移动项目时需要同步修改。
恢复 `backups/config-bottom.jsonc.before-space-delay` 并重新加载底栏可撤销占位时序修改。

`popup-effect.c` 随此库编译，为 GTK3 弹窗提供可选的 Wayland 模糊区域控制。只操作 ADWS 自己的表面，区域更新跟随 GTK 的下一次提交；不改变合成器配置。不支持协议或旧库缺少接口时回退。隐藏时释放效果对象，重新映射时绑定新表面，避免复用失效的 Wayland 对象。

模糊区域使用最多三块保守的内接矩形，圆角边框仍由 GTK 精确绘制；避免逐像素圆角区域把合成器的 damage 拆成大量片段。打开期间保持模糊区域固定；关闭时才随可见区域一起退场。
