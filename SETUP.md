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

## 3. Start it

1. Open the extracted **coach-dnunz-main** folder.
2. Double-click **start.bat**.
3. If a blue box says **"Windows protected your PC"**, click **More info**, then **Run anyway**.
   This happens because the file was downloaded from the internet.

A black window opens and shows what it is doing. **The first time, it downloads what it needs,
which can take a few minutes.** Then your web browser opens the app.

Keep the black window open while you use the app. Closing it stops the app.

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

- **Right side:** the rounds of each game. Click one to jump to it. Each round shows the score,
  whether it was won (**W**, green) or lost (**L**, red), and whether the spike was planted.
- **Under the video:** jump to the buy phase, live round, plant or round end of the round
  you're watching, or click the round clock to jump to a moment (it matches the in-game timer).
- **Skip dead time** jumps over menus, lobbies and timeouts while the video plays.
- Keyboard: `[` and `]` go to the previous and next round, `1` to `4` jump to the round's phases.

## Next time

Double-click **start.bat** again. It starts in a few seconds, and your library is still there.

## Getting a newer version

1. Download and extract the new ZIP (steps 1 and 2) into a new folder.
2. To keep your library, copy the **data** folder from your old coach-dnunz-main folder into the
   new one.
3. Start the new one with its **start.bat**.

## If something goes wrong

- **The browser didn't open.** Open your browser and go to **http://localhost:8000** (the black
  window shows the exact address).
- **The black window says the OCR engine could not load.** Install the Microsoft Visual C++
  Redistributable from **https://aka.ms/vs/17/release/vc_redist.x64.exe**, then double-click
  **start.bat** again.
- **The black window flashed and closed, or shows an error.** Check your internet connection and
  try again. If it keeps happening, take a screenshot of the black window and send it over.
- **A YouTube link failed.** Check that the video is public and the link opens in your browser,
  then click **Retry** on it. If you have the recording as a file, adding that instead is faster.
- **"No Valorant games found".** The video needs to show Valorant's normal in-game HUD (the timer
  and scores at the top of the screen). Broadcasts with a custom overlay may not be recognised.
- **Running out of disk space.** Delete videos you've finished with from the library (the **⋯**
  menu on each one). Their copies are removed from the **data** folder too.

## Stopping it

Close the black window.
