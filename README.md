# NFC Card Battler

A C# / .NET 10 terminal roguelite. Tap an NTAG215 card to load a character,
fight NPC enemies, then tap again to save. The card is the character's only
save file.

The current design and build order are in [the game spec](docs/NFC%20Card%20Battler%20-%20Game%20Spec.pdf).
The Python code in `outdated/` is old reference material and is not used by
this application.

## Getting started

See [the beginner setup guide](docs/Getting%20Started.md) for installing the
SDK, understanding the four projects, and the commands used to create them.

With the .NET 10 SDK installed, run these commands from this folder:

```powershell
dotnet build
dotnet run --project src/NfcBattler.Terminal
dotnet test
```

## Projects

| Project | Purpose |
| --- | --- |
| `NfcBattler.Core` | Battle engine, AI, and rules, independent of hardware and UI. |
| `NfcBattler.Cards` | NFC communication and card save format; references Core. |
| `NfcBattler.Terminal` | Console entry point; references Core and Cards. |
| `NfcBattler.Tests` | xUnit tests; references Core and Cards. |

The terminal now offers **Read**, **Write text**, **Clear**, and **Exit**. It uses PCSC 7.0.1
and Microsoft's Iot.Device.Bindings 4.2.0 from the spec. Plug in the ACR1552U,
choose an option, and follow the prompts with an NTAG215 card held on the reader.
Read displays the UID, NDEF records, and user-memory pages. Write asks for text
and explicit `WRITE` confirmation, then verifies the content by reading it back.

Writing replaces the NDEF message and requires an already formatted, writable
NTAG215. It never writes identity, formatting, lock, or configuration pages, and
refuses to replace a recognized NFC Battler game save. It is a basic NFC text
tool; character saves, battles, and the styled interface are still future work.

Clear asks you to type `CLEAR`, then erases all user pages (4-129), leaving an
empty NDEF message. It reads back the full user area to verify the erase.
Formatting, identity, lock, and configuration pages are preserved. Recognized
game saves are protected and reserved for the separate admin wipe tool.

GET_VERSION must return all eight bytes through the ACR1552U's pass-through
command. Unsupported firmware or truncated responses produce an error rather
than guessing the card type. The PCSC-only fallback mentioned in the spec is
not implemented yet. Real reader/card round trips still need hardware testing.
