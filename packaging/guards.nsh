; Shared with the local silent fixture that exercises Win32 file collision checks.
Var Pins
Var GuardPath
Var ProfileBoundary
Var ShortcutFile
Var SavedCopy
Var EmptyDir
Var SameBytes

!macro Stop
  MessageBox MB_ICONSTOP|MB_OK "$(Unsafe)" /SD IDOK
  SetErrorLevel 2
  Abort
!macroend

!macro CompareFiles PREFIX
Function ${PREFIX}CompareFiles
  StrCpy $SameBytes 0
  ClearErrors
  FileOpen $5 "$ShortcutFile" r
  IfErrors done
  FileOpen $6 "$SavedCopy" r
  IfErrors closeFirst
  FileSeek $5 0 END $7
  FileSeek $6 0 END $8
  IntCmp $7 0 different different 0
  IntCmp $7 $8 0 different different
  IntCmp $7 1048576 different 0 different
  FileSeek $5 0 SET
  FileSeek $6 0 SET
compare:
  IntCmp $7 0 equal
  FileReadByte $5 $8
  FileReadByte $6 $9
  IfErrors different
  StrCmp $8 $9 0 different
  IntOp $7 $7 - 1
  Goto compare
equal:
  StrCpy $SameBytes 1
different:
  FileClose $6
closeFirst:
  FileClose $5
done:
FunctionEnd
!macroend

!macro Guards PREFIX
Function ${PREFIX}Pin
  System::Call 'kernel32::CreateFileW(w R0, i 0x80, i 3, p 0, i 3, i 0x02200000, p 0) p .R1'
  IntCmp $R1 -1 invalid
  System::Call 'kernel32::GetFileAttributesW(w R0) i .R2'
  IntCmp $R2 -1 invalid
  IntOp $R2 $R2 & 0x410
  IntCmp $R2 16 0 invalid invalid
  ; Keep a list of pinned handles across section and MUI callbacks.
  System::Alloc 16
  Pop $R3
  StrCmp $R3 0 invalid
  System::Call '*$R3(p $Pins,p R1)'
  StrCpy $Pins $R3
  Return
invalid:
  !insertmacro Stop
FunctionEnd

Function ${PREFIX}PinChain
!ifdef RELOCATION_D
  StrCmp "$GuardPath" "${READER_PARENT}" readerDrive
  StrCmp "$GuardPath" "${READER_INSTALL}" readerDrive
  StrLen $1 "${READER_INSTALL}\"
  StrCpy $0 "$GuardPath" $1
  StrCmp "$0" "${READER_INSTALL}\" readerDrive
!endif
  StrLen $1 "$ProfileBoundary\"
  StrCpy $0 "$GuardPath" $1
  StrCmp "$0" "$ProfileBoundary\" +4
  !insertmacro Stop
  StrCpy $8 0
!ifdef RELOCATION_D
  Goto inspectDrive
readerDrive:
  StrCpy $8 1
inspectDrive:
!endif
  ${GetRoot} "$GuardPath" $0
  StrCpy $R0 "$0\"
  System::Call 'kernel32::GetDriveTypeW(w R0) i .r1'
  StrCmp $1 3 fixed
  StrCmp $8 1 invalidDrive
  StrCmp $1 2 fixed
  StrCmp $1 6 fixed
invalidDrive:
  !insertmacro Stop
fixed:
  Call ${PREFIX}Pin
  StrLen $1 $R0
again:
  StrCpy $2 "$GuardPath" 1 $1
  IntOp $1 $1 + 1
  StrCmp $2 "" done
  StrCmp $2 "\" folder
  StrCpy $R0 "$R0$2"
  Goto again
folder:
  Call ${PREFIX}Pin
  StrCpy $R0 "$R0\"
  Goto again
done:
  Call ${PREFIX}Pin
FunctionEnd

Function ${PREFIX}ReleasePins
loop:
  StrCmp $Pins 0 done
  System::Call '*$Pins(p .R3,p .R1)'
  System::Call 'kernel32::CloseHandle(p R1)'
  System::Free $Pins
  StrCpy $Pins $R3
  Goto loop
done:
FunctionEnd

; Check every occupied payload name before changing an existing installation.
; A read-only item, open executable, shared lock, link or directory collision
; must fail while the old application still has all of its files.
Function ${PREFIX}CheckFile
  System::Call 'kernel32::GetFileAttributesW(w R0) i .R2 ?e'
  Pop $R3
  IntCmp $R2 -1 missing
  IntOp $R2 $R2 & 0x411
  IntCmp $R2 0 0 invalid invalid
  System::Call 'kernel32::CreateFileW(w R0, i 0x40010080, i 7, p 0, i 3, i 0x00200000, p 0) p .R1'
  IntCmp $R1 -1 invalid
  System::Call 'kernel32::CloseHandle(p R1)'
  Return
missing:
  ; ERROR_FILE_NOT_FOUND or ERROR_PATH_NOT_FOUND are the only absent cases.
  IntCmp $R3 2 done
  IntCmp $R3 3 done
invalid:
  !insertmacro Stop
done:
FunctionEnd
!macroend

!macro OwnedUninstaller PREFIX
  StrCpy $ShortcutFile "$INSTDIR\Uninstall.exe"
  StrCpy $SavedCopy "$INSTDIR\uninstaller.copy"
  Call ${PREFIX}CompareFiles
  StrCmp $SameBytes 1 +4
  !insertmacro Stop
!macroend
