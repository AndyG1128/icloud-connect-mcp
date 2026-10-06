"""Deterministic synthetic protocol peers; no live credentials or personal data."""
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
import aiosmtplib


def synthetic_message():
    msg = EmailMessage()
    msg["From"] = "sender@example.invalid"
    msg["Reply-To"] = "reply@example.invalid"
    msg["To"] = "owner@example.invalid"
    msg["Subject"] = "Synthetic literal needle"
    msg["Message-ID"] = "<source@example.invalid>"
    msg["X-Repeated"] = "first"; msg["X-Repeated"] = "second"
    msg.set_content("Synthetic body needle. "*3000)
    msg.add_alternative("<p>Synthetic HTML</p>"*2000, subtype="html")
    msg.add_attachment(b"synthetic attachment bytes"*100, maintype="application", subtype="octet-stream", filename='example "name".bin')
    return msg.as_bytes()


class FakeIMAP:
    def __init__(self):
        self.boxes = {"INBOX": {1: synthetic_message()}, 'Archive/Quoted "Folder"': {41: synthetic_message(), 42: synthetic_message()}, "Sent Messages": {}}
        self.uv = {name: 100+i for i, name in enumerate(self.boxes)}
        self.next_uids = {name:max(box,default=0)+1 for name,box in self.boxes.items()}
        self.flagsets = {name: {uid:set() for uid in box} for name,box in self.boxes.items()}
        self.calls = []; self.selected = None; self.readonly = True
        self.use_uid = True
        self.capabilities = {"MOVE", "UIDPLUS"}; self.mutate_on_peek = False

    def list_folders(self):
        self.calls.append(("list_folders",))
        return [((), b"/", name) for name in self.boxes]

    def select_folder(self, name, readonly=False):
        self.calls.append(("select", name, readonly)); self.selected=name; self.readonly=readonly
        return {b"UIDVALIDITY":self.uv[name]}

    def search(self, criteria, charset=None):
        self.calls.append(("search", criteria, charset))
        if criteria[0] == 'HEADER':
            from email.parser import BytesParser
            return [uid for uid, raw in self.boxes[self.selected].items()
                    if criteria[2] in str(BytesParser().parsebytes(raw).get(criteria[1], ''))]
        if criteria[0] == 'UID':
            minimum=int(criteria[1].split(':')[0])
            return [uid for uid in self.boxes[self.selected] if uid>=minimum]
        return [uid for uid, raw in self.boxes[self.selected].items()
                if ("TEXT" not in criteria or criteria[1].encode(charset or 'ascii') in raw) and
                   ("UNSEEN" not in criteria or b"\\Seen" not in self.flagsets[self.selected][uid])]

    def fetch(self, uids, fields):
        self.calls.append(("fetch", list(uids), fields))
        out = {}
        for uid in uids:
            if uid not in self.boxes[self.selected]:continue
            # IMAPClient UID mode uses the UID as the mapping key and retains
            # only the mailbox sequence number inside each response row.
            row = {b"SEQ": list(self.boxes[self.selected]).index(uid) + 1}
            for field in fields:
                if field == "FLAGS":row[b"FLAGS"]=tuple(self.flagsets[self.selected][uid])
                elif field == "RFC822.SIZE":row[b"RFC822.SIZE"]=len(self.boxes[self.selected][uid])
                elif field == "INTERNALDATE":row[b"INTERNALDATE"]=datetime(2026,1,1,tzinfo=timezone.utc)
                elif field == "BODY.PEEK[]":
                    if self.mutate_on_peek:self.flagsets[self.selected][uid].add(b"\\Seen")
                    row[b"BODY[]"]=self.boxes[self.selected][uid]
                else:assert field=="UID"
            out[uid]=row
        return out

    def has_capability(self, name):return name in self.capabilities
    def folder_status(self, folder, fields):
        return {b'UIDVALIDITY':self.uv[folder], b'UIDNEXT':self.next_uid(folder)}
    def next_uid(self, folder):
        self.next_uids[folder]=max(self.next_uids[folder],max(self.boxes[folder],default=0)+1)
        return self.next_uids[folder]
    def logout(self):self.calls.append(("logout",))
    def shutdown(self):self.calls.append(("shutdown",))
    def add_flags(self, uids, flags, silent=True):
        assert not self.readonly
        self.calls.append(('add_flags', list(uids), list(flags), self.selected))
        for uid in uids:self.flagsets[self.selected][uid].update(flags)
    def remove_flags(self, uids, flags, silent=True):
        assert not self.readonly
        for uid in uids:self.flagsets[self.selected][uid].difference_update(flags)
    def move(self, uids, destination):
        assert not self.readonly; self.calls.append(("move",uids,destination))
        for uid in uids:
            target=max(self.boxes[destination],default=0)+1
            self.boxes[destination][target]=self.boxes[self.selected].pop(uid)
            self.flagsets[destination][target]=self.flagsets[self.selected].pop(uid)
    def uid_expunge(self, uids):
        assert not self.readonly; self.calls.append(("uid_expunge",uids))
        for uid in uids:
            if b"\\Deleted" in self.flagsets[self.selected][uid]:self.boxes[self.selected].pop(uid)
    def copy(self, uids, destination):
        self.calls.append(('copy', list(uids), destination))
        uid=uids[0]; target=self.next_uid(destination); self.next_uids[destination]=target+1
        self.boxes[destination][target]=self.boxes[self.selected][uid]
        self.flagsets[destination][target]=set(self.flagsets[self.selected][uid])
        return f'[COPYUID {self.uv[destination]} {uid} {target}] Copy completed'.encode()
    def append(self, folder, raw, flags=()):
        self.calls.append(('append', folder, raw, tuple(flags)))
        uid=self.next_uid(folder); self.next_uids[folder]=uid+1
        self.boxes[folder][uid]=raw; self.flagsets[folder][uid]=set(flags)
        return f'[APPENDUID {self.uv[folder]} {uid}] Append completed'.encode()
    def expunge(self,*args):raise AssertionError("Broad expunge is forbidden")


class FakeSMTP:
    def __init__(self):self.data_started=False;self.mode="ok";self.attempts=0;self.raw=None;self.recipients=None
    async def connect(self):
        if self.mode=="connect_failure":raise ConnectionError("PRIVATE authentication context")
    async def login(self,*args):pass
    async def sendmail(self,sender,recipients,raw):
        self.attempts+=1;self.raw=raw;self.recipients=recipients;self.data_started=True
        if self.mode=="ambiguous":raise ConnectionError("PRIVATE body")
        if self.mode=="rejected":raise aiosmtplib.errors.SMTPDataError(550,"PRIVATE rejection")
        return ({recipients[-1]:None} if self.mode=="partial" else {}),"PRIVATE server reply"
    def close(self):pass


class FakeCalendar:
    def __init__(self,client,index,components=("VEVENT",)):
        self.client=client;self.url=f"https://p01-caldav.icloud.com/123/calendars/calendar-{index}/"
        self.name="Synthetic calendar";self.components=components
    def get_supported_components(self,with_fallback=False):return self.components
    def get_properties(self, props, parse_props=True):
        from lxml import etree
        from caldav.elements import dav, cdav
        result = {}
        for prop in props:
            element = etree.Element(prop.tag)
            if prop.tag == dav.ResourceType.tag:
                etree.SubElement(element, '{DAV:}collection')
                etree.SubElement(element, '{urn:ietf:params:xml:ns:caldav}calendar')
            elif prop.tag == cdav.SupportedCalendarComponentSet.tag:
                for name in self.components:
                    etree.SubElement(element, '{urn:ietf:params:xml:ns:caldav}comp', name=name)
            elif prop.tag == dav.Owner.tag:
                etree.SubElement(element, '{DAV:}href').text = '/synthetic/principal/'
            result[prop.tag] = element
        return result
    def search(self,**kwargs):
        self.client.calls.append(("search",kwargs))
        return [SimpleNamespace(url=href) for href in self.client.resources if href.startswith(self.url)]


class FakeDAV:
    def __init__(self,raw):
        self.collections=[FakeCalendar(self,i, ("VTODO",) if i==5 else ("VEVENT",)) for i in range(6)]
        self.resources={self.collections[0].url+"example.ics": [raw.encode() if isinstance(raw,str) else raw, '"etag-1"']}
        self.calls=[];self.force_conflict=False;self.ambiguous=False
    def principal(self):return self
    def calendars(self):return self.collections
    def close(self):pass
    def request(self,url,method="GET",body="",headers=None):
        self.calls.append((method,url,headers))
        if method=="GET":
            if url not in self.resources:return SimpleNamespace(status=404,headers={},raw=b"")
            raw,etag=self.resources[url];return SimpleNamespace(status=200,headers={"ETag":etag},raw=raw)
        if self.ambiguous:raise ConnectionError("PRIVATE event description")
        if self.force_conflict or (headers.get("If-Match") and (url not in self.resources or self.resources[url][1]!=headers["If-Match"])) or (headers.get("If-None-Match")=="*" and url in self.resources):
            return SimpleNamespace(status=412,headers={},raw=b"")
        if method=="DELETE":self.resources.pop(url);return SimpleNamespace(status=204,headers={},raw=b"")
        assert method=="PUT";self.resources[url]=[body.encode(), '"etag-2"']
        return SimpleNamespace(status=201,headers={"ETag":'"etag-2"'},raw=b"")
