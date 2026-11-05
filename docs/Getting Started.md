# Starting the C# project

The current plan is in `NFC Card Battler - Game Spec.pdf`. The Python code in
`outdated/` is historical reference, not part of the C# application.

## The pieces

- **C#** is the language you write.
- **.NET 10** provides the libraries and runtime your C# program uses.
- **SDK** means software development kit: it includes the tools to create,
  compile, run, and test your code. A runtime alone cannot build projects.
- A **project** (`.csproj`) describes one application or library.
- A **solution** (`.slnx`) groups the four projects so you can build them together.
- A **project reference** lets one project use code from another.

## Install the tools

Install the .NET 10 SDK, then open a new PowerShell terminal:

```powershell
winget install --id Microsoft.DotNet.SDK.10 --exact --source winget
dotnet --list-sdks
```

The second command should include a version starting with `10.0.`.
If you use VS Code, install Microsoft's **C# Dev Kit** extension for editing
and debugging C#. The command-line steps below also work without that extension.

## Project layout

```text
NfcBattler.slnx
src/
  NfcBattler.Core/       Battle engine, enemy AI, and game rules
  NfcBattler.Cards/      NFC communication and the save format
  NfcBattler.Terminal/   Executable: the terminal game starts in Program.cs
tests/
  NfcBattler.Tests/      xUnit tests, runnable without a reader
```

Core has no project dependencies. Cards references Core. Terminal references
Core and Cards. Tests references Core and Cards. This keeps the game rules
independent of both the terminal and the physical NFC reader.

## Build, run, and test

Open PowerShell in the repository folder (the folder containing the solution):

```powershell
dotnet build
dotnet run --project src/NfcBattler.Terminal
dotnet test
```

`build` compiles the whole solution and reports errors. `run` starts the terminal
application. `test` runs the automated checks. The first build downloads test
packages from NuGet, so it needs internet access.

Start learning by changing the message in `src/NfcBattler.Terminal/Program.cs`,
then running the application again. `Console.WriteLine` prints a line of text.
The initial test only checks that the test runner works; it does not test game
behavior yet.

## How to create this structure yourself

These template commands create the same project structure. The starter files
in this repository were written directly while the SDK installer waited for
Windows approval. You do not need to rerun these commands here. Template
package versions and sample filenames may differ from the starter files.

```powershell
dotnet new sln --name NfcBattler
dotnet new classlib --name NfcBattler.Core --output src/NfcBattler.Core --framework net10.0
dotnet new classlib --name NfcBattler.Cards --output src/NfcBattler.Cards --framework net10.0
dotnet new console --name NfcBattler.Terminal --output src/NfcBattler.Terminal --framework net10.0
dotnet new xunit --name NfcBattler.Tests --output tests/NfcBattler.Tests --framework net10.0
dotnet sln add src/NfcBattler.Core/NfcBattler.Core.csproj src/NfcBattler.Cards/NfcBattler.Cards.csproj src/NfcBattler.Terminal/NfcBattler.Terminal.csproj tests/NfcBattler.Tests/NfcBattler.Tests.csproj
dotnet add src/NfcBattler.Cards reference src/NfcBattler.Core
dotnet add src/NfcBattler.Terminal reference src/NfcBattler.Core src/NfcBattler.Cards
dotnet add tests/NfcBattler.Tests reference src/NfcBattler.Core src/NfcBattler.Cards
```

`classlib` creates reusable code without an entry point. `console` creates an
executable with a `Program.cs` entry point. `xunit` creates a test project.

## Current NFC menu

Run the terminal application and choose **1** to read, **2** to write text,
**3** to clear, or **0** to exit. Place your NTAG215 on the reader when prompted and leave it there
until the operation finishes. Writing asks you to type `WRITE` after showing
the card UID, existing NDEF content, and new text. It replaces the NDEF message.

`Program.cs` handles the prompts. `NfcCardSession.cs` connects to the reader and
uses Microsoft's NDEF and Ultralight library to read/write. `PcscTransceiver.cs`
translates the library's commands into the reader's PC/SC commands. Tests use
simulated card memory to check these commands and NDEF text round trips.

This tool requires an already NDEF-formatted NTAG215 for writing. It does not
format or unlock cards. Clear asks for `CLEAR` confirmation, erases user pages
4-129 while leaving an empty NDEF message, and verifies every user byte. It
preserves formatting and protection settings and refuses recognized game saves.
GET_VERSION requires compatible ACR1552U firmware;
if it fails or returns a truncated response, the tool stops with an error.
Hardware compatibility and real writes must still be verified with your reader.
Character saves and the remaining step 2 backup tool come later.
