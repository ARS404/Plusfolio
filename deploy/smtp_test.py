"""Disposable SMTP capture for integration tests, never part of production startup."""
import asyncio,time,uuid
from pathlib import Path
ROOT=Path('/tmp/smtp-capture');ROOT.mkdir(exist_ok=True)
async def handle(reader,writer):
    async def reply(line):writer.write((line+'\r\n').encode());await writer.drain()
    await reply('220 plusfolio-smtp-test ESMTP')
    while raw:=await reader.readline():
        line=raw.decode(errors='replace').strip();command=line.split(' ',1)[0].upper()
        if command in {'EHLO','HELO'}:await reply('250-plusfolio-smtp-test');await reply('250 SIZE 1048576')
        elif command=='DATA':
            await reply('354 Send message');content=[]
            while part:=await reader.readline():
                if part==b'.\r\n':break
                content.append(part[1:] if part.startswith(b'..') else part)
                if sum(map(len,content))>1048576:break
            target=ROOT/(str(time.time_ns())+'-'+uuid.uuid4().hex+'.eml');target.write_bytes(b''.join(content));await reply('250 Accepted')
        elif command=='QUIT':await reply('221 Bye');break
        elif command in {'MAIL','RCPT','RSET','NOOP'}:await reply('250 OK')
        else:await reply('502 Unsupported')
    writer.close();await writer.wait_closed()
async def main():
    server=await asyncio.start_server(handle,'0.0.0.0',2525,limit=2*1024*1024)
    async with server:await server.serve_forever()
asyncio.run(main())
