Unicode true
RequestExecutionLevel user
SetCompressor /SOLID zlib
SetDateSave off
ManifestDPIAware true
Name "Chaessi Metadata Reader ${APP_VERSION}"
OutFile "${WORK}\release\Chaessi-Metadata-Reader-Setup-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\ChaessiMetadataReader"
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
!define MUI_WELCOMEPAGE_TEXT "$(InstallWelcome)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${WORK}\license-page.txt"
!define MUI_PAGE_CUSTOMFUNCTION_PRE DirectoryPre
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY
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
LangString InstallWelcome ${LANG_ENGLISH} "Install Reader for this Windows user. New installations use the standard per-user folder; you may choose another local folder. An existing verified installation keeps its location. Settings and connection details stay in your Windows profile."
LangString InstallWelcome ${LANG_KOREAN} "현재 Windows 사용자를 위해 리더를 설치합니다. 신규 설치는 표준 사용자별 폴더를 기본으로 하며 다른 로컬 폴더를 선택할 수 있습니다. 검증된 기존 설치 위치와 프로필의 설정·연결 정보는 유지됩니다."
LangString InstallWelcome ${LANG_JAPANESE} "現在の Windows ユーザー用にリーダーをインストールします。新規インストールは標準のユーザー別フォルダーを使用し、別のローカルフォルダーも選べます。確認済みの既存インストール先とプロファイルの設定・接続情報は維持されます。"

!include "guards.nsh"
!include "update.nsh"

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

!macro SetInstallBoundariesFunction PREFIX
Function ${PREFIX}SetInstallBoundaries
  StrCpy $InstallBoundary "$INSTDIR"
  ${GetParent} "$INSTDIR" $InstallParent
FunctionEnd
!macroend
!insertmacro SetInstallBoundariesFunction ""
!insertmacro SetInstallBoundariesFunction "un."

Function NormalizeInstallRoot
  ; NSIS GetFullPathName empties its output when an ancestor does not yet
  ; exist. Win32 GetFullPathNameW is lexical and preserves fresh destinations.
  ; Call only after the packaged helper has rejected unsafe raw spellings.
  System::Call 'kernel32::GetFullPathNameW(w "$INSTDIR", i ${NSIS_MAX_STRLEN}, w .r0, p 0) i .r1'
  IntCmp $1 0 invalid invalid 0
  IntCmp $1 ${NSIS_MAX_STRLEN} invalid 0 invalid
  StrCmp $0 "" invalid
  ; The validated root is never a drive root. Remove its optional separator
  ; so registration, helper scope and pinned boundaries use the same path.
  StrCpy $1 $0 1 -1
  StrCmp $1 "\" 0 +2
  StrCpy $0 $0 -1
  StrCpy $INSTDIR $0
  Return
invalid:
  !insertmacro Stop
FunctionEnd

Function DirectoryPre
  ; Updating an existing product never silently relocates it.
  StrCmp $UpdateMode "fresh" show
  Abort
show:
FunctionEnd

Function DirectoryLeave
  Call SetInstallBoundaries
  ; The packaged updater validates the selected local path, volume and any
  ; existing product before the install section is permitted to write files.
  !insertmacro RunUpdater "guard"
  !insertmacro RequireUpdateSuccess
  Call NormalizeInstallRoot
  Call SetInstallBoundaries
FunctionEnd

Function LocateExistingInstallation
  ; Read-only discovery of an existing registered root or a protected,
  ; interrupted fresh-install root. Never send a user path to the log.
  ClearErrors
  ExecWait '"$PLUGINSDIR\chaessi-update.exe" locate-installation --output "$PLUGINSDIR\install-root.txt"' $UpdateExit
  IfErrors 0 +4
  !insertmacro Stop
  ${If} $UpdateExit == 10
    Return
  ${EndIf}
  !insertmacro RequireUpdateSuccess
  ClearErrors
  FileOpen $0 "$PLUGINSDIR\install-root.txt" r
  IfErrors 0 +4
  !insertmacro Stop
  FileReadUTF16LE $0 $1
  FileClose $0
  StrCmp "$1" "" 0 +4
  !insertmacro Stop
  StrCpy $INSTDIR "$1"
FunctionEnd

Function .onInit
  !insertmacro Init ""
  !insertmacro AcquireUpdateMutex
  !insertmacro RestoreInstallerLanguage
  ; NSIS initializes this from the per-user default or an explicit /D choice.
  ; Both go through the identical packaged path/ownership checks below.
  ${If} $INSTDIR == ""
    StrCpy $INSTDIR "$LOCALAPPDATA\Programs\ChaessiMetadataReader"
  ${EndIf}
  !insertmacro StageUpdater
  Call LocateExistingInstallation
  Call SetInstallBoundaries
  !insertmacro RunUpdater "guard"
  ${If} $UpdateExit == 10
    Call RecordDisplayVersion
    MessageBox MB_ICONINFORMATION|MB_OK "$(UpdateCurrent)" /SD IDOK
    SetErrorLevel 0
    Quit
  ${ElseIf} $UpdateExit == 12
    StrCpy $UpdateMode "commit"
  ${ElseIf} $UpdateExit == 13
    StrCpy $UpdateMode "fresh-recovery"
  ${ElseIf} $UpdateExit == 3
  ${OrIf} $UpdateExit == 11
    StrCpy $UpdateMode "upgrade"
  ${ElseIf} $UpdateExit == 0
    StrCpy $UpdateMode "fresh"
  ${Else}
    !insertmacro UpdateStopped
  ${EndIf}
  ; Normalize only after strict raw-path validation; do not turn a rejected
  ; dot/device/ADS spelling into an accepted path before the helper sees it.
  Call NormalizeInstallRoot
  Call SetInstallBoundaries
  Call HideDesktopUnlessFresh
  ${IfNot} ${Silent}
    !insertmacro MUI_LANGDLL_DISPLAY
  ${EndIf}
FunctionEnd
Function un.onInit
  !insertmacro Init "un."
  !insertmacro AcquireUpdateMutex
  !insertmacro RestoreInstallerLanguage
  ; NSIS initializes the uninstaller's $INSTDIR from its original directory.
  ; Never redirect an old/copied remover to another registered installation.
  ReadRegStr $0 HKCU "${ARP}" "InstallLocation"
  StrCmp "$0" "$INSTDIR" +4
  !insertmacro Stop
  Call un.SetInstallBoundaries
  !insertmacro StageUpdater
  !insertmacro RunUpdater "uninstall-guard"
  !insertmacro RequireUpdateSuccess
FunctionEnd

!macro AppRoot PREFIX
  ; Root was validated by the packaged updater, never reconstructed from a
  ; developer drive letter. Keep the same selected/attested path throughout.
  Call ${PREFIX}SetInstallBoundaries
  StrCpy $R0 "$INSTDIR"
  Call ${PREFIX}Pin
  StrCpy $GuardPath "$INSTDIR"
  Call ${PREFIX}PinChain
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

Section "$(AppSection)" Application
  SectionIn RO
  ${If} $UpdateMode == "fresh-recovery"
    ; Only after the user proceeds through the wizard, roll back the exact
    ; hash-proven files of this interrupted fresh setup, then install normally.
    !insertmacro RunUpdater "fresh-recover"
    !insertmacro RequireUpdateSuccess
    StrCpy $UpdateMode "fresh"
  ${EndIf}
  ${If} $UpdateMode != "fresh"
    !insertmacro AppRoot ""
  ${EndIf}
  ${If} $UpdateMode == "upgrade"
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
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  WriteUninstaller "$PLUGINSDIR\reader-uninstaller.generated"
  IfErrors 0 +4
  !insertmacro Stop
  !insertmacro RunUpdater 'setup-begin --uninstaller "$PLUGINSDIR\reader-uninstaller.generated"'
  !insertmacro RequireUpdateSuccess
  !insertmacro AppRoot ""
  ; PinChain now retains every existing ancestor and this root without delete
  ; sharing. Re-attest the same leaf's owner/private ACL while those handles
  ; stay live: the first helper call alone cannot authorize a replaced root.
  !insertmacro RunUpdater 'setup-begin --uninstaller "$PLUGINSDIR\reader-uninstaller.generated"'
  !insertmacro RequireUpdateSuccess
  ; Uninstall leaves unrelated records in place. The updater has attested
  ; that any remaining directory contains no installed Reader files.
  !insertmacro InstallDir "$INSTDIR"
  !insertmacro InstallPayloadDirs
  SetOverwrite off
  !insertmacro InstallFiles
  SetOutPath "$INSTDIR"
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
  StrCmp $UpdateMode "fresh-recovery" done
  SectionSetText ${Desktop} ""
  SectionSetFlags ${Desktop} 0
done:
FunctionEnd

Function un.CheckRegistration
  ClearErrors
  ReadRegStr $0 HKCU "${ARP}" "InstallLocation"
  ReadRegStr $1 HKCU "${ARP}" "UninstallString"
  ${If} ${Errors}
  ${OrIf} $0 != "$INSTDIR"
  ${OrIf} $1 != '"$INSTDIR\Uninstall.exe"'
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
