"""Build the grounded pharmacology corpus for VMedA AI."""
import html, json, re
from pathlib import Path
from scripts.course_automation.build_biochemistry_ai import chunks

ROOT = Path(__file__).resolve().parents[2]
INCLUDED = {"general", "theory", "theory_answers", "lesson_14", "tables", "practicum", "recipes", "control_1", "control_3", "control_3_extra", "control_4", "control_5", "control_6", "credit_tickets", "tickets", "ticket_practice"}

def main():
    sections=json.loads((ROOT/'.course-automation/pharmacology/knowledge_sections.json').read_text(encoding='utf-8')); entries=[]; seen=set()
    for section in sections:
        if section['id'] not in INCLUDED: continue
        for item in section['lessons']:
            text=html.unescape(re.sub(r'<[^>]+>','',item['content'])).strip()
            if len(text)<80: continue
            for part, fragment in enumerate(chunks(text),1):
                key=re.sub(r'\W+','',fragment).casefold()
                if key in seen: continue
                seen.add(key); source=item.get('sources',['Фармакология'])[0]
                entries.append({'subject':'фармакология','title':f"{section['title']}: {item['title']}, фрагмент {part}",'text':fragment,'source':source.split(',')[0],'locator':source.partition(',')[2].strip() or 'раздел курса','method':'verified_course_text'})
    out={'subject':'pharmacology','visibility':'ai_only','entries':entries,'quality':{'deduplicated':True,'unanswered_tests_excluded':True,'current_drug_information_warning':True}}
    (ROOT/'generated_knowledge/pharmacology_ai.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'entries':len(entries),'characters':sum(len(x['text']) for x in entries)},ensure_ascii=False))
if __name__=='__main__': main()
