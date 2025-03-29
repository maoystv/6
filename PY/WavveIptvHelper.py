import sys
import requests
import json
import datetime
from urllib import parse

LOGIN_URL = "https://account-api.wavve.com/v0.9/signin/wavve?apikey=E5F3E0D30947AA5440556471321BB6D9&credential=none&device=pc&drm=wm&partner=pooq&pooqzone=none&region=kor&targetage=all"
#LOGIN_URL = "https://apis.wavve.com/login?apikey=E5F3E0D30947AA5440556471321BB6D9&client_version=6.0.1&device=pc&drm=wm&partner=pooq&pooqzone=none&region=kor&targetage=all"
SVC_URL = "https://apis.wavve.com/fz/streaming?device=pc&partner=pooq&apikey=E5F3E0D30947AA5440556471321BB6D9&credential={0}&service=wavve&pooqzone=none&region=kor&drm=none&targetage=all&contentid={1}&hdr=sdr&videocodec=avc&audiocodec=ac3&issurround=n&format=normal&withinsubtitle=n&contenttype=live&action=hls&protocol=hls&quality=auto&deviceModelId=Windows%2010&guid=1d191e5c-568a-11ed-b37d-92dd5a1cfeb9&lastplayid=46fa3c25a79145d088caebeeebbee4dc&authtype=cookie&isabr=y&ishevc=n"
EPG_URL = "https://apis.wavve.com/live/epgs?enddatetime={0}&genre=all&limit=500&offset=0&startdatetime={1}&apikey=E5F3E0D30947AA5440556471321BB6D9&client_version=7.0.40&device=pc&drm=wm&partner=pooq&pooqzone=none&region=kor&targetage=all"
LOGOUT_URL = "https://apis.pooq.co.kr/logout?apikey=E5F3E0D30947AA5440556471321BB6D9&credential={0}&device=pc&drm=wm&partner=pooq&pooqzone=none&region=kor&targetage=all"
#CHDETAIL_URL = "https://apis.pooq.co.kr/live/channels/{0}?device=pc&partner=pooq&pooqzone=none&region=kor&drm=wm&targetage=all&apikey=E5F3E0D30947AA5440556471321BB6D9&credential=none"
CHDETAIL_URL = "https://apis.wavve.com/live/channels/{0}?apikey=E5F3E0D30947AA5440556471321BB6D9&client_version=6.0.1&device=pc&drm=wm&partner=pooq&pooqzone=none&region=kor&targetage=all"

def doLogin(userId,password):
    try:
        payloads=json.loads('{{"type": "general","id": "{0}","pushid": "","password":"{1}","profile": "0"}}'.format(userId,password))
        response = requests.post(LOGIN_URL, json=payloads)
        jsonResp = json.loads(response.text)

        credential=jsonResp.get("credential")
        payloads = '{{"type": "credential","id": "{0}","pushid": "","password":"","profile": "0"}}'.format(credential)
        headers = {
            'Content-Type':'application/json; charset=UTF-8',
            'Wavve-Credential':'{0}'.format(credential)
            }
        response = requests.post(LOGIN_URL,data=payloads,headers=headers)
        jsonResp = json.loads(response.text)
        if jsonResp.get("needselectprofile") !='n':
            raise Exception("Unexpected server response.")
    except Exception as e:
        print(str(e))
        return None
    else:
        return credential

def doLogout(credential):
    try:
        url=LOGOUT_URL.format(parse.quote(credential))
        response = requests.options(url)
    except Exception as e:
        return False
    else:
        return True

def getEPG(start,end,credential):
    headers = {
        'Content-Type':'application/json; charset=UTF-8',
        'Wavve-Credential':'{0}'.format(credential)
        }
    #url=EPG_URL.format(parse.quote(end),parse.quote(start),parse.quote(credential))
    url=EPG_URL.format(parse.quote(end),parse.quote(start))
    response = requests.get(url,headers=headers)
    jsonResp = json.loads(response.text)
    jsonList = jsonResp.get("list")
    return jsonList

def getGenreText(chId):
    headers = {
        'Content-Type':'application/json; charset=UTF-8',
        'Wavve-Credential':'{0}'.format(credential)
        }
    url=CHDETAIL_URL.format(chId)
    response = requests.get(url,headers=headers)
    jsonResp = json.loads(response.text)
    return  jsonResp.get("genretext")

def getPlayURL(chId,credential):
    try:
        url=SVC_URL.format(parse.quote(credential),chId)
        response = requests.get(url)
        jsonResp = json.loads(response.text)
        playUrl = jsonResp.get("playurl")
        awsCookie = jsonResp.get("awscookie")
        awsCookie = jsonResp.get("awscookie").replace(';','&').replace(' ','')
    except Exception as e:
        print(str(e))
        return None
    else:
        return playUrl + '?' + awsCookie
    finally:
        pass
    

def createM3U(credential,outpath):
    try:
        start=datetime.datetime.today().strftime("%Y-%m-%d %H:%M")
        end=(datetime.datetime.today() + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        channelList = getEPG(start,end,credential)
        file = open(outpath,'w', encoding='utf8')
        file.write("#EXTM3U8\n")
        chNum=0
        for channel in channelList:
            chId = channel["channelid"]
            playUrl = getPlayURL(chId,credential)
            if playUrl != None:            
                chName = channel["channelname"]
                iconUrl = channel["channelimage"] if ( "http" in channel["channelimage"]) else "https://" + channel["channelimage"]
                groupTitle = getGenreText(chId)
                file.write('#EXTINF:-1 tvg-id="{0}" tvg-logo="{1}" group-title="{2}" tvg-chno="{3}",{4}\n'.format(chId, iconUrl, groupTitle,chNum, chName))
                file.write(playUrl + "\n")   
            chNum = chNum + 1   
    except Exception as e:
        print(str(e))
        return False
    else:
        return True
    finally:
        if not file.closed:
            file.close()
            
def xmlesc(txt):
    try:
        txt = txt.replace("&", "&amp;")
        txt = txt.replace("<", "&lt;")
        txt = txt.replace(">", "&gt;")
        txt = txt.replace('"', "&quot;")
        txt = txt.replace("'", "&apos;")
    except:
        return ""
    else:
        return txt
    finally:
        pass

def createEPG(credential,outpath):
    try:
        start=datetime.datetime.today().strftime("%Y-%m-%d %H:%M")
        end=(datetime.datetime.today() + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")

        print ("START:",start, "END:",end)
        channelList = getEPG(start,end,credential)
        file = open(outpath,'w', encoding='utf8')

        file.write('<?xml version="1.0" encoding="UTF-8" ?>\n')
        file.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        file.write('<tv generator-info-name="Raccoon\'s wavve tool v1.0">\n')
        cn=0
        for channel in channelList:
            chId = channel["channelid"]
            chName = xmlesc(channel["channelname"])
            file.write('  <channel id="{0}">\n'.format(chId))
            file.write('    <display-name>{0}</display-name>\n'.format(chName))
            file.write('    <display-name>{0}</display-name>\n'.format("WAVVE"))
            file.write('    <display-name>{0}</display-name>\n'.format(cn))
            file.write('    <display-name>{0} {1}</display-name>\n'.format(cn, chName))
            file.write('    <display-name>{0} {1}</display-name>\n'.format(cn, "WAVVE"))
            chImgUrl =  channel["channelimage"] if ("http" in channel["channelimage"]) else "https://" + channel["channelimage"] 
            file.write('    <icon src="{0}" />\n'.format(chImgUrl))
            file.write('  </channel>\n')
            cn = cn + 1
        
        for channel in channelList:
            chId = channel["channelid"]
            pgmList=channel["list"]
            for pgm in pgmList:
                sTitle = parse.unquote(pgm["title"])
                dtStart = datetime.datetime.strptime(pgm["starttime"], '%Y-%m-%d %H:%M')
                dtEnd = datetime.datetime.strptime(pgm["endtime"], '%Y-%m-%d %H:%M')
                sStart = dtStart.strftime("%Y%m%d%H%M%S")
                sEnd = dtEnd.strftime("%Y%m%d%H%M%S")
                try:
                    targetAge = int(pgm["targetage"])
                except ValueError:
                    targetAge = 0

                if targetAge == 0 :
                    sTargetAge ="all"
                else:
                    sTargetAge ="{0}over age".format(targetAge)

                file.write('  <programme start="' + sStart + ' +0900" stop="' + sEnd + ' +0900" channel="' + chId + '">\n')
                file.write('    <title lang="kr">' + xmlesc(sTitle) + '</title>\n')
                file.write('    <desc lang="kr">' + xmlesc(sTitle) + '\n' + sTargetAge + '</desc>\n')
                file.write('    <rating system="KMRB">\n')
                file.write('      <value>{0}</value>\n'.format(sTargetAge))
                file.write('    </rating>\n')
                file.write('  </programme>\n')
        file.write('</tv>')        
    except Exception as e:
        print(str(e))
        return False
    else:
        return True
    finally:
        file.close

if __name__ == '__main__':
    if len(sys.argv) < 5 :
        print('USAGE\n  python {0} userId password EPG|M3U "outPath" \n'.format(sys.argv[0]))
    else: 
        userId = sys.argv[1]
        password = sys.argv[2]
        target = sys.argv[3].lower()
        outPath = sys.argv[4]
        
        credential = doLogin(userId,password)
        if credential != None :
            if target == 'epg':
                if createEPG(credential,outPath):
                    print('EPG created!\n')
                else:
                    print('EPG creation failed!\n')
            elif 'm3u':
                if createM3U(credential,outPath):
                    print('M3U created!\n')
                else:
                    print('M3U creation failed!\n')
            else:
                print("Invalid argument - " + target)
            doLogout(credential)
        else :
            print('Login failed! please check userid/password and try again!')