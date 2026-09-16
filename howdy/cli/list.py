# List all models for a user

# Import required modules
import sys
import os
import json
import time
import builtins

# Get the absolute path and the username
path = os.path.dirname(os.path.realpath(__file__)) + "/.."
user = builtins.howdy_user

# Check if the models file has been created yet
if not os.path.exists(path + "/models"):
	print("Face models have not been initialized yet, please run:")
	print("\n\tsudo howdy -U " + user + " add\n")
	sys.exit(1)

# Path to the models file
enc_file = path + "/models/" + user + ".dat"

# Load and decrypt models via hardware-bound AES-256-GCM security module
sys.path.insert(0, path)
import security
encodings = security.load_user_models(user)
if not encodings:
	print("No face model known for the user " + user + ", please run:")
	print("\n\tsudo howdy -U " + user + " add\n")
	sys.exit(1)

# Print a header
print("Known face models for " + user + ":")
print("\n\t\033[1;29mID  Date                 Label\033[0m")

# Loop through all encodings and print info about them
for enc in encodings:
	# Start with a tab and print the id
	print("\t" + str(enc["id"]), end="")
	# Print padding spaces after the id
	print((4 - len(str(enc["id"]))) * " ", end="")
	# Format the time as ISO in the local timezone if present
	enc_time = enc.get("time")
	if enc_time:
		print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(enc_time)), end="")
	else:
		print("Recorded Model       ", end="")
	# End with the label
	print("  " + str(enc.get("label", "unlabeled")))

# Add a closing enter
print()
