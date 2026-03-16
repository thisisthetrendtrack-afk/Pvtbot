import os
import sys

# Fix all bad quotes in bot.py before running

with open(‘bot.py’, ‘rb’) as f:
data = f.read()

data = data.replace(b’\xe2\x80\x9c’, b’”’)
data = data.replace(b’\xe2\x80\x9d’, b’”’)
data = data.replace(b’\xe2\x80\x98’, b”’”)
data = data.replace(b’\xe2\x80\x99’, b”’”)

with open(‘bot.py’, ‘wb’) as f:
f.write(data)

print(“Quotes fixed! Starting bot…”)

# Now run bot.py

os.execlp(‘python3’, ‘python3’, ‘bot.py’)
