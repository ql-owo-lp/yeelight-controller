# yeelight-controller

This project is mainly used to control yeelight (wifi version) smartly.
You can define more flexible policy for yeelight, including:
- Turn on/off light base on the sunset/sunrise time.
- Turn on/off light when your phone is connected to home wifi (means you come back to home from outside)
- Dynamically change light brightness in a time range.

Policy example is defined in the controller file. Simply run it with python, no super user (sudo) permission required.
The YeelightEifiBulbLanCtrl.py is grabbed from Yeelight website.  The only change I made is to move the
initial example at the bottom of the file to __main__ block.

To use this script, you also need to turn on the developer mode of your yeelight on yeelight app. See yeelight website
for instruction.

License: AGPLv3
