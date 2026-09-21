# HelloWorld — Plugin API v1.0 sample

From the ADWS root / 在 ADWS 根目录运行：

```sh
./adws mplg build plugins/sample
./adws mplg install plugins/org.adws.sample.HelloWorld_1.0.0.mplg
./adws mplg run org.adws.sample.HelloWorld
```

Enable it in Components and plugins / 在组件与插件设置中启用。
The host passes settings as JSON, handles rendering, and resolves `locale/` keys.
See [Plugin API](../../docs/mplg-spec.md).
