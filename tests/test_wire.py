"""Verify the actual IMAP library's serialization/parser, not a hand-written quote helper."""
from types import SimpleNamespace
from imapclient import IMAPClient
import pytest


def test_actual_imapclient_quotes_folder_and_selects_readonly():
    client=object.__new__(IMAPClient);client.folder_encode=True
    client._imap=SimpleNamespace(untagged_responses={b'EXISTS':[b'1'], b'FLAGS':[b'(\\Seen)'], b'UIDVALIDITY':[b'123']})
    calls=[];client._command_and_check=lambda *args,**kwargs:calls.append((args,kwargs))
    result=client.select_folder('Archive/Quoted "Folder"',readonly=True)
    assert calls[0][0]==('select',b'"Archive/Quoted \\"Folder\\""',True)
    assert result[b'UIDVALIDITY']==123
    assert client._normalise_folder('旅行') .startswith(b'"&')


def test_actual_imapclient_uid_peek_and_body_response_parser():
    calls=[]
    class Wire:
        def _command(self,*args):calls.append(args);return 'tag'
        def _command_complete(self,*args):return 'OK',[]
        def _untagged_response(self,*args):return 'OK',[(b'1 (UID 42 BODY[] {3}',b'abc'),b')']
    client=object.__new__(IMAPClient);client._imap=Wire();client.use_uid=True;client.normalise_times=False
    result=client.fetch([42],['BODY.PEEK[]'])
    assert calls[0][0:2]==('UID','FETCH')
    assert 'BODY.PEEK[]' in calls[0][3]
    assert result[42][b'BODY[]']==b'abc'


def test_checked_tagged_no_is_distinct_from_unknown_imap_errors():
    from icloud_mcp.mail import IMAPClient as CheckedIMAPClient, NegativeIMAPResponse
    from icloud_mcp.mail_operations import negative_response
    import imaplib
    client=object.__new__(CheckedIMAPClient)
    with pytest.raises(NegativeIMAPResponse) as result:
        client._check_resp('OK', 'append', 'NO', [b'PRIVATE response'])
    assert negative_response(result.value) and 'PRIVATE' not in str(result.value)
    assert not negative_response(imaplib.IMAP4.error('unknown protocol error'))
    assert not negative_response(imaplib.IMAP4.abort('lost response'))
    assert client._check_resp('OK', 'append', 'OK', [b'accepted']) is None


def test_actual_imapclient_copy_append_and_expunge_are_quoted_and_uid_targeted():
    client=object.__new__(IMAPClient); client.folder_encode=True; client.use_uid=True
    client.has_capability=lambda name:name=='UIDPLUS'
    calls=[]
    client._command_and_check=lambda *a,**kw:calls.append((a,kw))
    folder='Archive/Quoted "Folder"'; raw=b'Subject: synthetic\r\n\r\nexact bytes\r\n'
    client.copy([42],folder)
    client.append(folder,raw,flags=[b'\\Seen'])
    client.uid_expunge([42])
    quoted=client._normalise_folder(folder)
    assert calls[0][0][0]=='copy' and calls[0][0][2]==quoted and calls[0][1]['uid'] is True
    assert calls[1][0][0]=='append' and calls[1][0][1]==quoted and calls[1][0][-1]==raw
    assert calls[2][0][0]=='EXPUNGE' and calls[2][0][1] in ('42',b'42') and calls[2][1]['uid'] is True
    assert len(calls[2][0])==2  # Never the broad EXPUNGE command without explicit UIDs.
