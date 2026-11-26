Unicode true
RequestExecutionLevel user
SetCompressor /SOLID zlib
SetDateSave off
ManifestDPIAware true
Name "Chaessi Metadata Reader Update"
OutFile "${WORK}\release\Chaessi-Metadata-Reader-Patch-x64.exe"
ShowInstDetails show

!include MUI2.nsh
!include LogicLib.nsh
!include x64.nsh
!define MUI_WELCOMEPAGE_TITLE "$(PatchTitle)"
!define MUI_WELCOMEPAGE_TEXT "$(PatchIntro)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "Japanese"

LangString PatchTitle ${LANG_ENGLISH} "Update Chaessi Metadata Reader"
LangString PatchTitle ${LANG_KOREAN} "채씨 메타데이터 리더 업데이트"
LangString PatchTitle ${LANG_JAPANESE} "チェシ メタデータリーダーを更新"
LangString PatchIntro ${LANG_ENGLISH} "Finish your work and close Reader normally before proceeding. The updater checks all installed files and supports only the approved starting build."
LangString PatchIntro ${LANG_KOREAN} "작업을 마치고 리더를 정상 종료한 뒤 진행하세요. 승인된 기준 빌드인지 설치 파일 전체를 확인합니다."
LangString PatchIntro ${LANG_JAPANESE} "作業を終えてリーダーを通常の手順で閉じてください。インストール済みの全ファイルを確認し、承認済みの対象ビルドのみ更新します。"
LangString Unsafe ${LANG_ENGLISH} "Close Reader normally and try again."
LangString Unsafe ${LANG_KOREAN} "리더를 정상 종료한 후 다시 시도하세요."
LangString Unsafe ${LANG_JAPANESE} "リーダーを通常の手順で閉じてから再実行してください。"
LangString UpdateUnsafe ${LANG_ENGLISH} "Update stopped. Close Reader normally. If the installation is changed or unsupported, use the latest approved full Setup."
LangString UpdateUnsafe ${LANG_KOREAN} "업데이트를 중단했습니다. 리더를 정상 종료하세요. 파일이 다르거나 지원하지 않는 빌드면 승인된 최신 전체 설치기를 사용하세요."
LangString UpdateUnsafe ${LANG_JAPANESE} "更新を中止しました。リーダーを閉じてください。ファイルが異なる場合や未対応ビルドの場合は承認済みの最新セットアップを使ってください。"

!include "guards.nsh"
!include "update.nsh"
!ifdef COMPACT_BOOTSTRAP
  !include "${WORK}\compact-stage.nsh"
  !macro DropClrVariable NAME
    System::Call 'kernel32::SetLastError(i 0)'
    System::Call 'kernel32::SetEnvironmentVariableW(w "${NAME}",p 0) i .r8 ?e'
    Pop $9
    ${If} $8 == 0
    ${AndIf} $9 != 203 ; ERROR_ENVVAR_NOT_FOUND
      !insertmacro Stop
    ${EndIf}
  !macroend
!endif

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ${IfNot} ${RunningX64}
    !insertmacro Stop
  ${EndIf}
  !insertmacro AcquireUpdateMutex
  ${IfNot} ${Silent}
    !insertmacro MUI_LANGDLL_DISPLAY
  ${EndIf}
FunctionEnd

Section
!ifdef COMPACT_BOOTSTRAP
  !insertmacro StageCompact
  SetOutPath "$PLUGINSDIR\payload"
!else
  !insertmacro StageUpdater
  SetOutPath "$PLUGINSDIR\patch-payload"
!endif
  ClearErrors
  File "${PAYLOAD}\ChaessiMetadataReader.exe"
  IfErrors 0 +4
  !insertmacro Stop
!ifdef COMPACT_BOOTSTRAP
  ; These are removed only from the installer/child process environment.
  !insertmacro DropClrVariable COR_ENABLE_PROFILING
  !insertmacro DropClrVariable COR_PROFILER
  !insertmacro DropClrVariable COR_PROFILER_PATH
  !insertmacro DropClrVariable COR_PROFILER_PATH_32
  !insertmacro DropClrVariable COR_PROFILER_PATH_64
  !insertmacro DropClrVariable APPDOMAIN_MANAGER_ASM
  !insertmacro DropClrVariable APPDOMAIN_MANAGER_TYPE
  !insertmacro DropClrVariable COMPLUS_InstallRoot
  !insertmacro DropClrVariable COMPLUS_Version
  !insertmacro DropClrVariable DEVPATH
  ClearErrors
  ExecWait '"$PLUGINSDIR\patch-bootstrap.exe"' $UpdateExit
  IfErrors 0 +4
  !insertmacro Stop
!else
  !insertmacro RunUpdater 'patch --payload "$PLUGINSDIR\patch-payload"'
!endif
  !insertmacro RequireUpdateSuccess
SectionEnd
