# gameAgent
auto script basic on pyautogy and tesseract

can input name or index to execute the script

the script strcture:
gamefolder/gamepictures(png)
game2folder/gamepictures(png)
遊戲腳本.py

script save in folder

script form
wait1 #wait one second,number can change
scrollup/scrolldown
otherwise find picture in gamefolder
use#can specific the index if pictures in screen have multiple
use@can use OCR to double check the text in picture,contains 

exsample:
daily:{quest,wait1,subQuest,wait1,evolveQuest,wait1,evolve2@II,confirm,wait1,auto,wait1,skip#2,max,wait1,ok,toQuest}
