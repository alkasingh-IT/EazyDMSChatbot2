import re

with open('../DMSAIChat (1).jsx', encoding='utf-8') as f:
    content = f.read()

# Remove the React import line (hooks are global via UMD)
content = re.sub(r'^import\s+\{[^}]+\}\s+from\s+"react";\r?\n', '', content, count=1)

# Remove export default
content = content.replace('export default function DMSAIChat', 'function DMSAIChat')

with open('DMSAIChatInlined.jsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done. Lines:', content.count('\n'))
