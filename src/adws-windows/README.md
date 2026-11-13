# ADWS Windows native MVP

Experimental Windows x64 host, Win32 backend and replaceable out-of-process WM.
See [architecture, protocol, build and VM acceptance guide](../../docs/windows-native-mvp.md).

```powershell
./build.ps1
```

The build runs isolated layout/protocol/process tests and publishes to `artifacts/win-x64`.
Run the host with `--test-session` **only in a VM or dedicated test account**.
No shell registry installation or Explorer termination is implemented.
The current prototype needs .NET 8 Desktop Runtime x64. Existing Linux components are unchanged.
