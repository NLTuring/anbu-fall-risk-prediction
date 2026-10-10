import io
import sys

p = sys.argv[1] if len(sys.argv) > 1 else 'tools/content.py'
bad = 0
with io.open(p, encoding='utf-8') as f:
    for i, line in enumerate(f, 1):
        code = line.rstrip('\n')
        if code.count("'") % 2 == 1:
            print('%5d  %s' % (i, code[:120]))
            bad += 1
print('unbalanced lines:', bad)
sys.exit(1 if bad else 0)
