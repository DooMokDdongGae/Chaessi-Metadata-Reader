; Common bootstrap. The child updater takes its own per-user transaction lock.
Var UpdateExit
Var UpdateMode

!macro AcquireNamedSetupMutex name
  System::Call 'kernel32::SetLastError(i 0)'
  System::Call 'kernel32::CreateMutexW(p 0,i 0,w "${name}") p .r7 ?e'
  Pop $8
  StrCmp $7 0 0 +4
  !insertmacro Stop
  IntCmp $8 183 0 +4 +4
  !insertmacro Stop
!macroend

!macro AcquireUpdateMutex
  !insertmacro AcquireNamedSetupMutex "Local\CHAESSI.MetadataReader.Setup"
!macroend

!macro StageUpdater
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  File /oname=chaessi-update.exe "${UPDATER_EXE}"
  IfErrors 0 +4
  !insertmacro Stop
!macroend

!macro RunUpdater ARGS
  ClearErrors
  ExecWait '"$PLUGINSDIR\chaessi-update.exe" --install-root "$INSTDIR" ${ARGS}' $UpdateExit
  IfErrors 0 +4
  !insertmacro Stop
!macroend

!macro UpdateStopped
  DetailPrint "Reader update procedure returned $UpdateExit."
  MessageBox MB_ICONSTOP|MB_OK "$(UpdateUnsafe)" /SD IDOK
  SetErrorLevel $UpdateExit
  Abort
!macroend

!macro RequireUpdateSuccess
  ${If} $UpdateExit != 0
    !insertmacro UpdateStopped
  ${EndIf}
!macroend
