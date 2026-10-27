"""Contract shared by API reference and OpenAPI."""
PROPERTIES={
 'kind':{'type':'string','enum':['circle','worksheet','topic'],'description':'Сущность: кружки, версии листков или темы. Для задач используйте /problem-search, field=metadata.'},
 'q':{'type':'string','minLength':1,'maxLength':160,'pattern':r'\S','description':'Название, описание, смысловая формулировка или ID. ID и UUID ищутся точно, без векторов.'},
 'scope':{'type':'string','default':'available','enum':['available','public','mine','all','my','issued'],'description':'Для листков: available — доступный каталог; public — опубликованные; mine — мои текущие; all — текущие всех авторов, только админ; my — назначения школьника; issued — выданные выбранным circle. Для кружков/тем только available.'},
 'mode':{'type':'string','enum':['hybrid','text'],'default':'hybrid','description':'Текст и CPU-эмбеддинги либо только текст. До 3 символов используется текст. При сбое модели возвращаются текстовые результаты и notice.'},
 'limit':{'type':'integer','minimum':1,'maximum':100,'default':30,'description':'Первые результаты по релевантности, без общего count и страниц.'},
 'state':{'type':'string','enum':['active','all'],'default':'all','description':'Для кружков: только активные или вместе с архивом. Применяется до ранжирования.'},
 'city':{'type':'array','items':{'type':'string'},'description':'Точные города кружков, ИЛИ.'},
 'tag':{'type':'array','items':{'type':'integer'},'description':'ID тегов справочника circle или worksheet. Несколько тегов — ИЛИ. У тем тегов нет.'},
 'topic':{'type':'array','items':{'type':'string','format':'uuid'},'description':'Темы листков вместе с потомками, ИЛИ.'},
 'circle':{'type':'array','items':{'type':'string','format':'uuid'},'description':'Для scope=issued — доступные кружки. Чужие кружки не расширяют доступ.'},
}
PARAMETERS=[{'name':name,'in':'query','required':name in {'kind','q'},'schema':value,'description':value['description'],
             **({'style':'form','explode':True} if value['type']=='array' else {})} for name,value in PROPERTIES.items()]
DESCRIPTION='Гибридный поиск названий и описаний кружков/листков и полных путей тем с локальной CPU-моделью. Права, область каталога и фильтры применяются до ранжирования и фрагментов. Новые или изменённые данные доступны по тексту сразу, векторы обновляются в фоне. semantic сообщает участие модели, pending — число доступных документов без актуального вектора, notice — ограничения. До 60 запросов/минуту на аккаунт. Токен read_only разрешён. ФИО пользователей и приглашения не индексируются.'
