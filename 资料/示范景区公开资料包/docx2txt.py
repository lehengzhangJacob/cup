import sys
from docx import Document

if len(sys.argv) < 2:
    print("Usage: python docx2txt.py <input.docx> [output.txt]")
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.rsplit('.', 1)[0] + '.txt'

try:
    doc = Document(input_file)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(full_text))
    
    print(f"Successfully converted to {output_file}")
except Exception as e:
    print(f"Error: {e}")
