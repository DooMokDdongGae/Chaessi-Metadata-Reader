Unicode true
RequestExecutionLevel user
SetCompressor /SOLID zlib
SetDateSave off
ManifestDPIAware true
Name "Chaessi Metadata Reader ${APP_VERSION}"
!define RELOCATION_D
!define READER_VOLUME "D:\"
!define READER_PARENT "D:\MApp"
!define READER_INSTALL "D:\MApp\Chaessi Reader"
!define RELOCATION_MUTEX "Local\CHAESSI.MetadataReader.Relocation.Setup"
!define FINALIZE_FLAG "/FINALIZE-RELOCATION"
!define CANCEL_FLAG "/CANCEL-RELOCATION"
OutFile "${WORK}\release\Chaessi-Metadata-Reader-Setup-x64.exe"
InstallDir "${READER_INSTALL}"
ShowInstDetails show
ShowUninstDetails show

!include MUI2.nsh
!include LogicLib.nsh
!include FileFunc.nsh
!include x64.nsh
!define APP "ChaessiMetadataReader.exe"
!define ID "chaessi-metadata-reader-{328AA667-9BAC-42AA-8124-525AD9EB95D2}"
!define ARP "Software\Microsoft\Windows\CurrentVersion\Uninstall\ChaessiMetadataReader"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "Chaessi Metadata Reader"
VIAddVersionKey /LANG=1033 "FileDescription" "Chaessi Metadata Reader Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "Comments" "Build ${BUILD_ID}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "CHAESSI"
!define MUI_WELCOMEPAGE_TEXT "$(RelocationWelcome)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${WORK}\license-page.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "Japanese"

LangString AppSection ${LANG_ENGLISH} "Reader and Start menu shortcuts"
LangString AppSection ${LANG_KOREAN} "리더와 시작 메뉴 바로가기"
LangString AppSection ${LANG_JAPANESE} "リーダーとスタートメニューのショートカット"
LangString DesktopSection ${LANG_ENGLISH} "Desktop shortcut"
LangString DesktopSection ${LANG_KOREAN} "바탕 화면 바로가기"
LangString DesktopSection ${LANG_JAPANESE} "デスクトップのショートカット"
LangString Unsafe ${LANG_ENGLISH} "Setup stopped. Close Reader and check that its installation folder is accessible, belongs to Reader, and contains no redirected paths."
LangString Unsafe ${LANG_KOREAN} "작업을 중단했습니다. 리더를 닫고 설치 폴더에 접근할 수 있는지, 리더의 폴더인지, 연결된 경로가 있는지 확인하세요."
LangString Unsafe ${LANG_JAPANESE} "処理を中止しました。リーダーを閉じ、インストール先がアクセス可能なリーダー専用のフォルダーであり、リダイレクトされたパスを含まないことを確認してください。"
LangString Need64 ${LANG_ENGLISH} "This edition requires 64-bit Windows."
LangString Need64 ${LANG_KOREAN} "이 에디션은 64비트 Windows에서 실행됩니다."
LangString Need64 ${LANG_JAPANESE} "このエディションには64ビットのWindowsが必要です。"
LangString UpdateUnsafe ${LANG_ENGLISH} "Setup stopped. Close Reader normally. Use the latest approved Setup if this installation is newer, changed or needs recovery."
LangString UpdateUnsafe ${LANG_KOREAN} "설치를 중단했습니다. 리더를 정상 종료하세요. 더 새 빌드, 파일 변경 또는 복구가 필요한 경우 승인된 최신 설치기를 사용하세요."
LangString UpdateUnsafe ${LANG_JAPANESE} "セットアップを中止しました。リーダーを通常の手順で閉じてください。新しいビルドや変更、復旧がある場合は承認済みの最新セットアップを使ってください。"
LangString UpdateCurrent ${LANG_ENGLISH} "Reader ${APP_VERSION} is already installed. No files need to be replaced."
LangString UpdateCurrent ${LANG_KOREAN} "리더 ${APP_VERSION}이(가) 이미 설치되어 있습니다. 교체할 파일이 없습니다."
LangString UpdateCurrent ${LANG_JAPANESE} "Reader ${APP_VERSION} はインストール済みです。交換するファイルはありません。"
LangString UpdateApplied ${LANG_ENGLISH} "The existing Reader installation was updated."
LangString UpdateApplied ${LANG_KOREAN} "기존 리더 설치본을 업데이트했습니다."
LangString UpdateApplied ${LANG_JAPANESE} "既存のリーダーを更新しました。"
LangString UpdateRolledBack ${LANG_ENGLISH} "The update did not finish. The previous Reader files were restored."
LangString UpdateRolledBack ${LANG_KOREAN} "업데이트를 완료하지 못해 이전 리더 파일을 복원했습니다."
LangString UpdateRolledBack ${LANG_JAPANESE} "更新が完了しなかったため、以前のリーダーのファイルに戻しました。"
LangString RegistrationIncomplete ${LANG_ENGLISH} "Reader files are installed, but Windows could not record the version. Run this Setup again to finish registration."
LangString RegistrationIncomplete ${LANG_KOREAN} "리더 파일을 설치했지만 Windows가 버전을 기록하지 못했습니다. 이 설치기를 다시 실행해 등록을 완료하세요."
LangString RegistrationIncomplete ${LANG_JAPANESE} "リーダーのファイルはインストールされましたが、Windowsにバージョンを記録できませんでした。同じセットアップをもう一度実行してください。"
LangString RelocationWelcome ${LANG_ENGLISH} "This Setup installs Chaessi Metadata Reader in ${READER_INSTALL}. Close Reader normally before continuing. Your settings and connection details stay in your Windows profile."
LangString RelocationWelcome ${LANG_KOREAN} "리더를 ${READER_INSTALL}에 설치합니다. 계속하기 전에 리더를 정상 종료하세요. 설정과 연결 정보는 기존 Windows 프로필에 보존됩니다."
LangString RelocationWelcome ${LANG_JAPANESE} "リーダーを ${READER_INSTALL} にインストールします。続行する前にリーダーを通常の手順で終了してください。設定と接続情報は現在の Windows プロファイルに保持されます。"
LangString RelocationTrialReady ${LANG_ENGLISH} "The trial Reader is ready. The C-drive installation is still registered. Close Reader, then open ${READER_INSTALL}\${APP} to test it. Close the trial Reader and run this same Setup again when you are ready to finish the move."
LangString RelocationTrialReady ${LANG_KOREAN} "D 드라이브의 시험용 리더가 준비됐습니다. Windows에는 기존 C 설치가 등록돼 있습니다. 리더를 닫은 뒤 ${READER_INSTALL}\${APP}를 직접 열어 시험하세요. 시험이 끝나면 리더를 닫고 같은 설치기를 다시 실행하세요."
LangString RelocationTrialReady ${LANG_JAPANESE} "D ドライブの試用版リーダーの準備ができました。Windows には引き続き C ドライブのインストールが登録されています。リーダーを閉じ、${READER_INSTALL}\${APP} を直接開いて動作を確認してください。確認後、リーダーを閉じ、同じセットアップをもう一度実行してください。"
LangString RelocationConfirm ${LANG_ENGLISH} "Have you tested Reader from ${READER_INSTALL} and closed it? Choose Yes to finish the move and remove the previous C-drive installation. Choose No to leave the trial ready for further testing."
LangString RelocationConfirm ${LANG_KOREAN} "${READER_INSTALL}에서 리더를 직접 실행해 시험을 마쳤고 리더를 닫으셨나요? 예를 누르면 D 드라이브 이전을 완료하고 기존 C 설치를 제거합니다. 아니요를 누르면 시험 상태를 그대로 유지합니다."
LangString RelocationConfirm ${LANG_JAPANESE} "${READER_INSTALL} のリーダーを直接起動して動作を確認し、終了しましたか？「はい」で移行を完了し、C ドライブの以前のインストールを削除します。「いいえ」で試用状態を維持します。"
LangString RelocationFlagInvalid ${LANG_ENGLISH} "Use ${FINALIZE_FLAG} or ${CANCEL_FLAG} separately, only when the trial Reader is ready."
LangString RelocationFlagInvalid ${LANG_KOREAN} "시험용 리더가 준비된 뒤 ${FINALIZE_FLAG} 또는 ${CANCEL_FLAG} 중 하나만 사용하세요."
LangString RelocationFlagInvalid ${LANG_JAPANESE} "試用版リーダーの準備ができてから、${FINALIZE_FLAG} または ${CANCEL_FLAG} のいずれか一方を指定してください。"
LangString RelocationComplete ${LANG_ENGLISH} "Reader moved to ${READER_INSTALL}."
LangString RelocationComplete ${LANG_KOREAN} "리더를 ${READER_INSTALL}로 이전했습니다."
LangString RelocationComplete ${LANG_JAPANESE} "リーダーを ${READER_INSTALL} に移行しました。"
LangString RelocationCancelled ${LANG_ENGLISH} "Reader relocation was cancelled. The existing C-drive installation remains registered."
LangString RelocationCancelled ${LANG_KOREAN} "리더 이전을 취소했습니다. Windows에는 기존 C 설치가 등록돼 있습니다."
LangString RelocationCancelled ${LANG_JAPANESE} "リーダーの移行を取り消しました。Windows には C ドライブの既存のインストールが引き続き登録されています。"
LangString RelocationRecovered ${LANG_ENGLISH} "Reader relocation recovery finished. Check the Reader location in Windows before launching it."
LangString RelocationRecovered ${LANG_KOREAN} "리더 이전 복구가 끝났습니다. 실행하기 전에 Windows에서 리더 설치 위치를 확인하세요."
LangString RelocationRecovered ${LANG_JAPANESE} "リーダーの移行の復旧が完了しました。起動する前に Windows でインストール場所を確認してください。"
LangString RelocationRestored ${LANG_ENGLISH} "Reader could not be moved. The previous installation was restored."
LangString RelocationRestored ${LANG_KOREAN} "리더 이전을 완료하지 못해 이전 설치를 복원했습니다."
LangString RelocationRestored ${LANG_JAPANESE} "リーダーを移行できなかったため、以前のインストールを復元しました。"
LangString RelocationRecovery ${LANG_ENGLISH} "Reader relocation stopped before recovery finished. Reopen this same relocation Setup to resume recovery. Keep the existing files and settings."
LangString RelocationRecovery ${LANG_KOREAN} "리더 이전 중 복구를 완료하지 못했습니다. 이번에 사용한 D 드라이브 이전용 설치기를 다시 열어 복구를 이어가세요. 기존 파일과 설정을 보존하세요."
LangString RelocationRecovery ${LANG_JAPANESE} "移行中の復旧が完了していません。同じ移行セットアップを開いて復旧を再開してください。既存のファイルと設定は保持してください。"

!include "guards.nsh"
!include "update.nsh"

Var RelocationRequest

!macro StopRelocation code message
  DetailPrint "$(${message})"
  MessageBox MB_ICONSTOP|MB_OK "$(${message})" /SD IDOK
  SetErrorLevel ${code}
  Abort
!macroend

!macro RequireRelocationSuccess
  ${If} $UpdateExit == 4
    !insertmacro StopRelocation 4 "RelocationRestored"
  ${ElseIf} $UpdateExit == 5
    !insertmacro StopRelocation 5 "RelocationRecovery"
  ${EndIf}
  !insertmacro RequireUpdateSuccess
!macroend

!macro FinishRelocation message
  DetailPrint "$(${message})"
  MessageBox MB_ICONINFORMATION|MB_OK "$(${message})" /SD IDOK
  SetErrorLevel 0
  Quit
!macroend

; Never remove or replace a pre-existing shortcut. For shortcuts created by
; Reader, compare with the original bytes so subsequent user changes survive.
Function MakeOwnedLink
  ; Input: ShortcutFile, SavedCopy, and $5 (the absolute shortcut target).
  IfFileExists "$ShortcutFile" done
  ClearErrors
  CreateShortcut "$ShortcutFile" "$5"
  IfErrors failed
  System::Call 'kernel32::CopyFileW(w "$ShortcutFile", w "$SavedCopy", i 1) i .r6'
  StrCmp $6 0 failed
done:
  Return
failed:
  !insertmacro Stop
FunctionEnd

!insertmacro CompareFiles "un."

Function un.RemoveOwnedLink
  IfFileExists "$SavedCopy" 0 done
  Call un.CompareFiles
  StrCmp $SameBytes 1 0 +2
  Delete "$ShortcutFile"
  Delete "$SavedCopy"
done:
FunctionEnd

!macro Shortcut shortcut saved target
  StrCpy $ShortcutFile "${shortcut}"
  StrCpy $SavedCopy "$INSTDIR\${saved}"
  StrCpy $5 "${target}"
  Call MakeOwnedLink
!macroend
!macro UnShortcut shortcut saved
  StrCpy $ShortcutFile "${shortcut}"
  StrCpy $SavedCopy "$INSTDIR\${saved}"
  Call un.RemoveOwnedLink
!macroend

; Pin every existing path component without FILE_SHARE_DELETE. The attribute
; check runs while the handle is held so a directory cannot be renamed away.

!macro InstallDir path
  CreateDirectory "${path}"
  StrCpy $R0 "${path}"
  Call Pin
!macroend
!macro RemoveDir path
  IfFileExists "${path}\." 0 +3
  StrCpy $R0 "${path}"
  Call un.Pin
!macroend
!macro UpdateDir path
  IfFileExists "${path}\." 0 +3
  StrCpy $R0 "${path}"
  Call Pin
!macroend
!macro RemoveEmpty path
  ${If} ${FileExists} "${path}\."
    StrCpy $EmptyDir "${path}"
    ${GetParent} "$EmptyDir" $GuardPath
    Call un.PinChain
    System::Call 'kernel32::GetFileAttributesW(w "$EmptyDir") i .r6'
    IntOp $6 $6 & 0x400
    IntCmp $6 0 0 +2 +2
    RMDir "$EmptyDir"
    Call un.ReleasePins
  ${EndIf}
!macroend
!macro InstallFile rel
  ; Fresh install never overwrites an existing path.
  IfFileExists "$INSTDIR\${rel}" 0 +4
  !insertmacro Stop
  ClearErrors
  File "${PAYLOAD}\${rel}"
  IfErrors 0 +4
  !insertmacro Stop
!macroend
!include "${WORK}\files.nsh"

!insertmacro Guards ""
!insertmacro Guards "un."

!macro Init PREFIX
  SetShellVarContext current
  SetRegView 64
  StrCpy $Pins 0
  StrCpy $ProfileBoundary "$PROFILE"
  StrCpy $INSTDIR "${READER_INSTALL}"
  !insertmacro AcquireNamedSetupMutex "${RELOCATION_MUTEX}"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "$(Need64)" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
!macroend

!macro RestoreInstallerLanguage
  ReadRegStr $0 HKCU "${ARP}" "InstallerLanguage"
  ${If} $0 == ${LANG_ENGLISH}
  ${OrIf} $0 == ${LANG_KOREAN}
  ${OrIf} $0 == ${LANG_JAPANESE}
    StrCpy $LANGUAGE $0
  ${EndIf}
!macroend

Function RecordDisplayVersion
  ; Called only after the protected updater verifies or commits the target.
  ReadRegStr $0 HKCU "${ARP}" "DisplayVersion"
  StrCmp $0 "${APP_VERSION}" done
  ClearErrors
  WriteRegStr HKCU "${ARP}" "DisplayVersion" "${APP_VERSION}"
  IfErrors 0 done
  MessageBox MB_ICONSTOP|MB_OK "$(RegistrationIncomplete)" /SD IDOK
  SetErrorLevel 6
  Abort
done:
FunctionEnd

Function ReadRelocationRequest
  ; Only exact command-line tokens can authorize removal of the old installation.
  StrCpy $RelocationRequest ""
  System::Call 'kernel32::GetCommandLineW() p .R1'
  System::Call 'shell32::CommandLineToArgvW(p R1, *i .R2) p .R0'
  StrCmp $R0 0 invalid
  StrCpy $R3 $R0
nextArgument:
  IntOp $R2 $R2 - 1
  IntCmp $R2 0 done freeInvalid 0
  IntOp $R3 $R3 + ${NSIS_PTR_SIZE}
  System::Call '*$R3(p .R4)'
  System::Call 'kernel32::lstrcpynW(w .R5, p R4, i 64) p'
  StrCmp "$R5" "${FINALIZE_FLAG}" finalize
  StrCmp "$R5" "${CANCEL_FLAG}" cancel
  StrCpy $R6 "$R5" 3
  StrCmp "$R6" "/D=" pathOverride
  StrLen $R6 "${FINALIZE_FLAG}"
  StrCpy $R7 "$R5" $R6
  StrCmp "$R7" "${FINALIZE_FLAG}" freeInvalid
  StrLen $R6 "${CANCEL_FLAG}"
  StrCpy $R7 "$R5" $R6
  StrCmp "$R7" "${CANCEL_FLAG}" freeInvalid nextArgument
finalize:
  StrCmp "$RelocationRequest" "" 0 freeInvalid
  StrCpy $RelocationRequest "commit"
  Goto nextArgument
cancel:
  StrCmp "$RelocationRequest" "" 0 freeInvalid
  StrCpy $RelocationRequest "cancel"
  Goto nextArgument
pathOverride:
  ; NSIS consumes the rest of the command line as the /D path.
  StrCmp "$RelocationRequest" "" done freeInvalid
done:
  System::Call 'kernel32::LocalFree(p R0) p'
  Return
freeInvalid:
  System::Call 'kernel32::LocalFree(p R0) p'
invalid:
  !insertmacro StopRelocation 2 "RelocationFlagInvalid"
FunctionEnd

Function FinishTrial
  ${If} $RelocationRequest == ""
    ${If} ${Silent}
      !insertmacro FinishRelocation "RelocationTrialReady"
    ${EndIf}
    MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON2 "$(RelocationConfirm)" /SD IDNO IDYES confirmed
    !insertmacro FinishRelocation "RelocationTrialReady"
  ${EndIf}
  ${If} $RelocationRequest == "cancel"
    !insertmacro RunUpdater "relocate --operation cancel"
    !insertmacro RequireRelocationSuccess
    !insertmacro FinishRelocation "RelocationCancelled"
  ${EndIf}
confirmed:
  !insertmacro RunUpdater "relocate --operation commit"
  !insertmacro RequireRelocationSuccess
  !insertmacro FinishRelocation "RelocationComplete"
FunctionEnd

Function .onInit
  !insertmacro Init ""
  !insertmacro RestoreInstallerLanguage
  Call ReadRelocationRequest
  !insertmacro StageUpdater
  !insertmacro RunUpdater "relocate-guard"
  ${If} $UpdateExit == 20
    ${If} $RelocationRequest != ""
      !insertmacro StopRelocation 2 "RelocationFlagInvalid"
    ${EndIf}
    StrCpy $UpdateMode "relocation-stage"
  ${ElseIf} $UpdateExit == 21
    ; The C-drive uninstaller must be free to acquire its standard mutex.
    Call FinishTrial
  ${ElseIf} $UpdateExit == 22
    ${If} $RelocationRequest != ""
      !insertmacro StopRelocation 2 "RelocationFlagInvalid"
    ${EndIf}
    !insertmacro RunUpdater "relocate --operation recover"
    !insertmacro RequireRelocationSuccess
    !insertmacro FinishRelocation "RelocationRecovered"
  ${ElseIf} $UpdateExit == 5
    !insertmacro StopRelocation 5 "RelocationRecovery"
  ${Else}
    !insertmacro RequireUpdateSuccess
    ${If} $RelocationRequest != ""
      !insertmacro StopRelocation 2 "RelocationFlagInvalid"
    ${EndIf}
    !insertmacro AcquireUpdateMutex
    !insertmacro RunUpdater "guard"
    ${If} $UpdateExit == 10
      Call RecordDisplayVersion
      MessageBox MB_ICONINFORMATION|MB_OK "$(UpdateCurrent)" /SD IDOK
      SetErrorLevel 0
      Quit
    ${ElseIf} $UpdateExit == 12
      StrCpy $UpdateMode "commit"
    ${ElseIf} $UpdateExit == 3
    ${OrIf} $UpdateExit == 11
      StrCpy $UpdateMode "upgrade"
    ${ElseIf} $UpdateExit == 0
      StrCpy $UpdateMode "fresh"
    ${Else}
      !insertmacro UpdateStopped
    ${EndIf}
  ${EndIf}
  Call HideDesktopUnlessFresh
  ${IfNot} ${Silent}
    !insertmacro MUI_LANGDLL_DISPLAY
  ${EndIf}
FunctionEnd
Function un.onInit
  !insertmacro Init "un."
  !insertmacro AcquireUpdateMutex
  !insertmacro RestoreInstallerLanguage
  !insertmacro StageUpdater
  !insertmacro RunUpdater "uninstall-guard"
  !insertmacro RequireUpdateSuccess
FunctionEnd

!macro AppRoot PREFIX
  ; Never use /D or persisted registry strings as filesystem targets.
  StrCpy $INSTDIR "${READER_INSTALL}"
  StrCmp "$LOCALAPPDATA" "$PROFILE\AppData\Local" +4
  !insertmacro Stop
  StrCpy $R0 "${READER_VOLUME}"
  System::Call 'kernel32::GetDriveTypeW(w R0) i .r1'
  StrCmp $1 3 +4
  !insertmacro Stop
  Call ${PREFIX}Pin
  ${If} ${FileExists} "${READER_PARENT}\."
    StrCpy $GuardPath "${READER_PARENT}"
    Call ${PREFIX}PinChain
  ${EndIf}
!macroend
!macro ProductMarker
  ClearErrors
  FileOpen $3 "$INSTDIR\product.id" r
  IfErrors 0 +4
  !insertmacro Stop
  FileRead $3 $4
  FileClose $3
  StrCmp "$4" "${ID}" +4
  !insertmacro Stop
!macroend

Function StageRelocationOwnership
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  WriteUninstaller "$PLUGINSDIR\reader-uninstaller.generated"
  IfErrors 0 +4
  !insertmacro Stop
  StrCpy $0 "en"
  StrCmp $LANGUAGE ${LANG_KOREAN} 0 +2
  StrCpy $0 "ko"
  StrCmp $LANGUAGE ${LANG_JAPANESE} 0 +2
  StrCpy $0 "ja"
  ; Set the working directory for the staged links without creating D folders.
  StrCpy $OUTDIR "$INSTDIR"
  ClearErrors
  CreateShortcut "$PLUGINSDIR\reader-start.lnk" "$INSTDIR\${APP}"
  IfErrors 0 +4
  !insertmacro Stop
  ClearErrors
  CreateShortcut "$PLUGINSDIR\reader-guide.lnk" "$INSTDIR\docs\README.$0.html"
  IfErrors 0 +4
  !insertmacro Stop
  ClearErrors
  CreateShortcut "$PLUGINSDIR\reader-desktop.lnk" "$INSTDIR\${APP}"
  IfErrors 0 +4
  !insertmacro Stop
  SetOutPath "$PLUGINSDIR"
FunctionEnd

Section "$(AppSection)" Application
  SectionIn RO
  !insertmacro AppRoot ""
  ${If} $UpdateMode == "relocation-stage"
    !insertmacro StageFiles
    Call StageRelocationOwnership
    !insertmacro RunUpdater 'relocate --operation stage --payload "$PLUGINSDIR\payload" --uninstaller "$PLUGINSDIR\reader-uninstaller.generated" --start-link "$PLUGINSDIR\reader-start.lnk" --guide-link "$PLUGINSDIR\reader-guide.lnk" --desktop-link "$PLUGINSDIR\reader-desktop.lnk" --installer-language $LANGUAGE'
    !insertmacro RequireRelocationSuccess
    DetailPrint "$(RelocationTrialReady)"
    MessageBox MB_ICONINFORMATION|MB_OK "$(RelocationTrialReady)" /SD IDOK
    Goto done
  ${ElseIf} $UpdateMode == "upgrade"
    !insertmacro StageFiles
    SetOutPath "$PLUGINSDIR"
    ClearErrors
    WriteUninstaller "$PLUGINSDIR\reader-uninstaller.generated"
    IfErrors 0 +4
    !insertmacro Stop
    !insertmacro RunUpdater 'setup-apply --payload "$PLUGINSDIR\payload" --uninstaller "$PLUGINSDIR\reader-uninstaller.generated"'
    ${If} $UpdateExit == 4
      DetailPrint "$(UpdateRolledBack)"
      MessageBox MB_ICONSTOP|MB_OK "$(UpdateRolledBack)" /SD IDOK
      SetErrorLevel 4
      Abort
    ${EndIf}
    !insertmacro RequireUpdateSuccess
    Call RecordDisplayVersion
    DetailPrint "$(UpdateApplied)"
    Goto done
  ${ElseIf} $UpdateMode == "commit"
    !insertmacro RunUpdater "setup-commit"
    !insertmacro RequireUpdateSuccess
    Call RecordDisplayVersion
    Goto done
  ${EndIf}
  ; Recheck before a fresh wizard writes files; leave existing installations
  ; to the shared updater, even if they appeared after .onInit.
  !insertmacro RunUpdater "guard"
  !insertmacro RequireUpdateSuccess
  !insertmacro RunUpdater "setup-begin"
  !insertmacro RequireUpdateSuccess
  !insertmacro InstallDir "${READER_PARENT}"
  ; Uninstall leaves unrelated records in place. The updater has attested
  ; that any remaining directory contains no installed Reader files.
  !insertmacro InstallDir "$INSTDIR"
  !insertmacro InstallPayloadDirs
  SetOverwrite off
  !insertmacro InstallFiles
  SetOutPath "$INSTDIR"
  InitPluginsDir
  ClearErrors
  WriteUninstaller "$PLUGINSDIR\reader-uninstaller.generated"
  IfErrors 0 +4
  !insertmacro Stop
  ; CopyFile with bFailIfExists never writes through a colliding link or file.
  System::Call 'kernel32::CopyFileW(w "$PLUGINSDIR\reader-uninstaller.generated", w "$INSTDIR\Uninstall.exe", i 1) i .r6'
  StrCmp $6 0 0 +4
  !insertmacro Stop
  System::Call 'kernel32::CopyFileW(w "$PLUGINSDIR\reader-uninstaller.generated", w "$INSTDIR\uninstaller.copy", i 1) i .r6'
  StrCmp $6 0 0 +4
  !insertmacro Stop
  WriteRegStr HKCU "${ARP}" "DisplayName" "Chaessi Metadata Reader"
  WriteRegStr HKCU "${ARP}" "Publisher" "CHAESSI"
  WriteRegStr HKCU "${ARP}" "DisplayIcon" "$INSTDIR\${APP}"
  WriteRegStr HKCU "${ARP}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${ARP}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${ARP}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${ARP}" "NoModify" 1
  WriteRegDWORD HKCU "${ARP}" "NoRepair" 1

  StrCpy $GuardPath "$SMPROGRAMS"
  Call PinChain
  !insertmacro InstallDir "$SMPROGRAMS\Chaessi Metadata Reader"
  !insertmacro Shortcut "$SMPROGRAMS\Chaessi Metadata Reader\Chaessi Metadata Reader.lnk" "start-link.copy" "$INSTDIR\${APP}"
  StrCpy $0 "en"
  StrCmp $LANGUAGE ${LANG_KOREAN} 0 +2
  StrCpy $0 "ko"
  StrCmp $LANGUAGE ${LANG_JAPANESE} 0 +2
  StrCpy $0 "ja"
  !insertmacro Shortcut "$SMPROGRAMS\Chaessi Metadata Reader\Guide.lnk" "guide-link.copy" "$INSTDIR\docs\README.$0.html"
  Call ReleasePins
  !insertmacro RunUpdater "setup-commit"
  !insertmacro RequireUpdateSuccess
  Call RecordDisplayVersion
  WriteRegStr HKCU "${ARP}" "InstallerLanguage" "$LANGUAGE"
done:
SectionEnd

Section /o "$(DesktopSection)" Desktop
  StrCmp $UpdateMode "fresh" 0 done
  !insertmacro AppRoot ""
  StrCpy $GuardPath "$INSTDIR"
  Call PinChain
  StrCpy $GuardPath "$DESKTOP"
  Call PinChain
  !insertmacro Shortcut "$DESKTOP\Chaessi Metadata Reader.lnk" "desktop-link.copy" "$INSTDIR\${APP}"
  Call ReleasePins
done:
SectionEnd

Function HideDesktopUnlessFresh
  StrCmp $UpdateMode "fresh" done
  SectionSetText ${Desktop} ""
  SectionSetFlags ${Desktop} 0
done:
FunctionEnd

Function un.CheckRegistration
  ClearErrors
  ReadRegStr $0 HKCU "${ARP}" "InstallLocation"
  ReadRegStr $1 HKCU "${ARP}" "UninstallString"
  ${If} ${Errors}
  ${OrIf} $0 != "${READER_INSTALL}"
  ${OrIf} $1 != '"${READER_INSTALL}\Uninstall.exe"'
    !insertmacro Stop
  ${EndIf}
FunctionEnd

Section "Uninstall"
  !insertmacro AppRoot "un."
  Call un.CheckRegistration
  !insertmacro RemoveDir "$INSTDIR"
  !insertmacro ProductMarker
  !insertmacro RemovePayloadDirs
  !insertmacro CheckFiles "un."
  ; uninstall-guard already streams and attests both large uninstaller copies.
  ; CompareFiles below remains restricted to small shortcut copies.
  !insertmacro RemoveFiles
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\uninstaller.copy"
  StrCpy $GuardPath "$SMPROGRAMS"
  Call un.PinChain
  !insertmacro RemoveDir "$SMPROGRAMS\Chaessi Metadata Reader"
  !insertmacro UnShortcut "$SMPROGRAMS\Chaessi Metadata Reader\Guide.lnk" "guide-link.copy"
  !insertmacro UnShortcut "$SMPROGRAMS\Chaessi Metadata Reader\Chaessi Metadata Reader.lnk" "start-link.copy"
  ${If} ${FileExists} "$INSTDIR\desktop-link.copy"
    StrCpy $GuardPath "$DESKTOP"
    Call un.PinChain
    !insertmacro UnShortcut "$DESKTOP\Chaessi Metadata Reader.lnk" "desktop-link.copy"
  ${EndIf}
  Call un.ReleasePins
  SetOutPath "$TEMP"
  !insertmacro RemoveEmptyDirs
  !insertmacro RemoveEmpty "$INSTDIR"
  !insertmacro RemoveEmpty "$SMPROGRAMS\Chaessi Metadata Reader"
  Call un.CheckRegistration
  DeleteRegKey HKCU "${ARP}"
SectionEnd
