# HelloWorld — Plugin API v1.0 sample

From the MNWS root / 在 MNWS 根目录运行：

```sh
./mnws mplg build plugins/sample
./mnws mplg install plugins/org.mnws.sample.HelloWorld_1.0.0.mplg
./mnws mplg run org.mnws.sample.HelloWorld
```

Enable it in Components and plugins / 在组件与插件设置中启用。
The host passes settings as JSON, handles rendering, and resolves `locale/` keys.
See [Plugin API](../../docs/mplg-spec.md).
