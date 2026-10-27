"""Shared public descriptions and illustrative data for both search transports."""
from copy import deepcopy

SEARCH_PROPERTIES = {
    'q': {'type':'string','minLength':1,'maxLength':12000,'pattern':r'\S',
          'description':'Непустой текст условия/решения или ID P-123/UUID. Пробелы по краям удаляются. Число без префикса в field=solution ищется как текст ответа, в остальных полях — как номер задачи/источника.'},
    'field': {'type':'string','enum':['all','statement','solution','metadata'],'default':'all',
              'description':'Где искать: all — названия, описания, условия и разрешённые решения; metadata — название и описание; statement — только условия; solution — только разрешённые решения. Учитываются обычный текст и TeX.'},
    'fields':{'type':'array','items':{'type':'string','enum':['statement','solution','metadata']},'default':[], 'description':'Необязательный набор полей; непустой массив имеет приоритет над field. В JSON массив, в GET повторяемый fields.'},
    'scope': {'type':'string','enum':['library','my'],'default':'library',
              'description':'library — задачи в пределах текущих прав; my — только персональные назначения, нужна роль student. Аккаунт без teacher/analyst/admin всегда ограничен my. Несколько ролей объединяют доступ.'},
    'mode': {'type':'string','enum':['hybrid','text'],'default':'hybrid',
             'description':'hybrid объединяет текстовый поиск и локальные CPU-эмбеддинги; text использует только текст. При недоступной модели hybrid возвращает текстовые результаты с notice, HTTP 200.'},
    'limit': {'type':'integer','minimum':1,'maximum':50,'default':20,
              'description':'Максимум результатов, по умолчанию 20. Выдача отсортирована по релевантности, пагинации и общего count нет. Меньше limit не означает, что дублей гарантированно нет.'},
    'tag': {'type':'array','items':{'type':'integer'},'default':[],
            'description':'Числовые ID тегов задач из /tags: выбирайте записи kind=problem. В JSON — массив, в GET — повторяемый tag. Несколько тегов работают как ИЛИ; фильтры разных видов — как И.'},
    'topic': {'type':'array','items':{'type':'string','format':'uuid'},'default':[],
              'description':'UUID тем из /topics, включая потомков выбранных узлов. В JSON — массив, в GET — повторяемый topic. Несколько веток объединяются как ИЛИ. Пустой массив не ограничивает поиск.'},
}

SEARCH_BODY = {'type':'object','properties':deepcopy(SEARCH_PROPERTIES),'required':['q'],
               'description':'JSON-тело поиска. Обязателен только q; пропущенные поля получают значения по умолчанию. POST читает данные и разрешён токену read_only.'}

SEARCH_PARAMETERS = [
    {'name':name,'in':'query','required':name=='q','description':schema['description'],'schema':deepcopy(schema),
     **({'style':'form','explode':True} if schema['type']=='array' else {})}
    for name,schema in SEARCH_PROPERTIES.items()
]

SEARCH_DESCRIPTION = (
    'Поиск по доступным условиям и решениям: текстовые совпадения и локальная CPU-модель. '
    'Закрытые задачи и решения исключаются до ранжирования и формирования фрагментов. '
    'При нескольких ролях права объединяются; scope=my требует роли student. '
    'Возвращаются первые limit результатов без общего count и пагинации. '
    'match — способ совпадения, а не вероятность дубля. Материалы не создаются и не объединяются. '
    'Если модель недоступна, возвращаются текстовые результаты с semantic=false и notice, HTTP 200; '
    'pending сообщает число доступных документов выбранных полей, ожидающих индексации. При поиске по ID эти метаданные не вычисляются: semantic=false, pending=0, notice пустой. '
    'Оба метода разрешены токену read_only. До 60 запросов в минуту на аккаунт в текущем Django cache; '
    'для нескольких web-процессов общий лимит требует общего cache backend. При 429 учитывайте Retry-After.'
)

SEARCH_EXAMPLE = {'q':'Как доказать, что сумма двух чётных чисел тоже чётная?',
                  'field':'statement','scope':'library','mode':'hybrid','limit':5,'tag':[],'topic':[]}

EXAMPLE_ID = '00000000-0000-4000-8000-000000000012'
EXAMPLE_TOPIC = '00000000-0000-4000-8000-000000000001'
EXAMPLE_PROBLEM = {
    'id':EXAMPLE_ID,'public_id':'P-12','title':'Чётная сумма','description':'Иллюстративный пример, не данные пользователя.',
    'author':'Автор примера','archived':False,'topics':[EXAMPLE_TOPIC],'tags':[],
    'custom_title':'Чётная сумма','number':12,'source':'','source_id':'','source_url':'','attribution':{},
    'statement':'Докажите, что сумма двух чётных целых чисел чётна.', 'statement_tex':'','source_format':'plain',
    'pdf_url':f'/api/v1/materials/problem/{EXAMPLE_ID}/pdf',
    'tex_url':f'/api/v1/materials/problem/{EXAMPLE_ID}/tex',
    'project_url':f'/api/v1/materials/problem/{EXAMPLE_ID}/project',
}
SEARCH_RESPONSE_EXAMPLE = {
    'results':[{'problem':EXAMPLE_PROBLEM,'match':'semantic','fields':['statement'],
                'excerpt':EXAMPLE_PROBLEM['statement']}],
    'semantic':True,'pending':0,'notice':'',
}
