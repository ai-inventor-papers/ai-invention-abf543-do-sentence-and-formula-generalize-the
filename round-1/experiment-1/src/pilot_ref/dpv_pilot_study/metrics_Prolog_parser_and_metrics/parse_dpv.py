


with open("DPV_terms.txt") as f:
    text = f.read()

text = text.split()
text = [f"\"{word.replace(",", "")}\"," for word in text]
text = ' '.join(text)
text = "[" + text[:-1] + "]"
#print(text)

with open("dpv_terms.json", "w") as f:
    f.write(text)