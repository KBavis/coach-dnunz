# Setting up Coach Dnunz

Coach Dnunz breaks a Valorant match recording into games and rounds so you can jump straight to
any round, and to its buy phase, live round, plant or round end. It runs entirely on your own
computer. These steps are for Windows. Nothing needs to be installed beforehand.

## What you need

- A Windows 10 or 11 PC
- An internet connection the first time you start it
- Free disk space: about 1 GB for the app, plus room for your videos (a 3-hour YouTube stream
  is about 7 GB)

## 1. Download it

1. Open the project's GitHub page: **https://github.com/KBavis/coach-dnunz**
2. Click the green **Code** button, then **Download ZIP**.

## 2. Unzip it

1. Open your **Downloads** folder and find **coach-dnunz-main.zip**.
2. Right-click it and choose **Extract All…**, pick a place you'll find again (for example your
   Documents folder), and click **Extract**.

Make sure you extract it. Opening the zip and double-clicking files inside it won't work.

## 3. Start it the first time

You only do this once. Afterwards you'll use a **Coach Dnunz** icon on your desktop.

1. Open the extracted **coach-dnunz-main** folder.
2. Double-click the file named **start** whose type is **Windows Batch File**.

   There are three files called "start". Windows usually hides the end of file names, so look at
   the **Type** column (switch to **View → Details** if you don't see it) and pick the one that
   says **Windows Batch File**, not "Windows PowerShell Script" or "SH File". If your Windows does
   show file endings, it's the one called **start.bat**.
3. If a blue box says **"Windows protected your PC"**, click **More info**, then **Run anyway**.
   This happens because the file was downloaded from the internet.

A black window opens and shows what it is doing. **The first time, it downloads what it needs,
which can take a few minutes.** Then:

- your web browser opens the app,
- a **Coach Dnunz** icon appears on your **desktop** and in the **Start menu**,
- and the black window **closes by itself**.

The app keeps running in the background. You'll see its icon (a blue diamond) by the clock in the
bottom-right corner of the screen. It may be hidden under the small **^** arrow there.

## 4. Add your recordings

1. Click **+ Add VODs**.
2. Choose **Video files** to add recordings from your computer. This is the fastest way:
   processing starts right away. Or choose **YouTube links** and paste one link per box (use
   **+ Add another link** for more). YouTube videos have to download first, which takes longer.
3. Click **Process VODs**.

Each video shows its progress (download, scan, find rounds, results). A 3-hour match takes a few
minutes. Each one appears in your library when it's ready. You can keep using the app meanwhile.

## 5. Review a match

Click a video in the library to open it.

- **Right side:** the games (each tab shows **W** or **L** for the game) and their rounds. Click a
  round to jump to it. Each round shows the score, whether it was won (**W**, green) or lost
  (**L**, red), and whether the spike was planted. A game the video cuts off shows no result.
- **Under the video:** jump to the buy phase, live round, plant or round end of the round
  you're watching, or click the round clock to jump to a moment (it matches the in-game timer).
- **Skip dead time** jumps over menus, lobbies and timeouts while the video plays.
- Keyboard: `[` and `]` go to the previous and next round, `1` to `4` jump to the round's phases.

## Next time

Double-click the **Coach Dnunz** icon on your desktop (or find **Coach Dnunz** in the Start menu).
It opens in your browser within a few seconds, and your library is still there.

If it's already running, the icon just opens it again. You can also click the blue diamond by the
clock and choose **Open Coach Dnunz**.

## Getting a newer version

1. Quit Coach Dnunz: right-click the blue diamond by the clock, then **Quit**.
2. Download and extract the new ZIP (steps 1 and 2) into a new folder.
3. To keep your library, copy the **data** folder from your old coach-dnunz-main folder into the
   new one.
4. Double-click the new folder's **start** file (type **Windows Batch File**) once. This updates
   the desktop icon so it opens the new version. After that, use the icon as usual.

## If something goes wrong

- **The browser didn't open.** Click the blue diamond by the clock and choose **Open Coach
  Dnunz**, or open your browser and go to **http://localhost:8000**.
- **The desktop icon does nothing, or you moved the folder.** Double-click the **start** file
  (type **Windows Batch File**) in the coach-dnunz-main folder again. It fixes the icon.
- **The black window says the OCR engine could not load.** Install the Microsoft Visual C++
  Redistributable from **https://aka.ms/vs/17/release/vc_redist.x64.exe**, then double-click
  the **start** file (type **Windows Batch File**) again.
- **The black window shows an error (and stays open).** Check your internet connection and try
  again. If it keeps happening, take a screenshot of the black window and send it over.
- **Something else isn't working.** Right-click the blue diamond by the clock and choose **Show
  log**, then send that file over.
- **A YouTube link failed.** Check that the video is public and the link opens in your browser,
  then click **Retry** on it. If you have the recording as a file, adding that instead is faster.
- **"No Valorant games found".** The video needs to show Valorant's normal in-game HUD (the timer
  and scores at the top of the screen). Broadcasts with a custom overlay may not be recognised.
- **Running out of disk space.** Delete videos you've finished with from the library (the **⋯**
  menu on each one). Their copies are removed from the **data** folder too.

## Stopping it

Right-click the blue diamond by the clock (it may be under the **^** arrow) and choose **Quit**.
This also stops any video that is still processing; it picks up again next time you start.
