import httpx
import asyncio
import json

# Auto-generated clean microservice API client

async def post_bf_4639051e_746e_412b_a942_74bd22627eea(payload: dict = None, custom_headers: dict = None):
    url = "https://agclus.mamda-mcma.ma:9999/bf/4639051e-746e-412b-a942-74bd22627eea?type=js3&sn=v_4_srv_-2D23437_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU&svrid=-23437&flavor=cors&vi=FUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0&modifiedSince=1786682541133&bp=3&app=bc3ee5199b8b91f5&crc=3385903488&en=av00743p&end=1"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "*/*",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "text/plain;charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "connection": "keep-alive"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_FrontExpert_listeMissions(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/listeMissions"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab20007448cc0823a830c2e98e7290f37c94edecc721b68606d8c83610d3eae14d5f79082bf8d34411300035e58dc3e6660407e87d56748dbc87b0b4b03bcb93fbbfefc28bc9adfc81b02643675c97270111d143096a5c0619238e; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def get_SinAuto_MCMA_expertise_notification_alerte(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/alerte"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/",
    "x-requested-with": "XMLHttpRequest",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab20007448cc0823a830c2e98e7290f37c94edecc721b68606d8c83610d3eae14d5f79082bf8d34411300035e58dc3e6660407e87d56748dbc87b0b4b03bcb93fbbfefc28bc9adfc81b02643675c97270111d143096a5c0619238e; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.get(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_listeMissionExpert(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeMissionExpert"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000dfd5212eb3f093e9597c11e9449ec51d6b712eeb5f5e044187d4237238cc57d70852aef4f311300064fd319b32b28f8884312e02bea72f5d49d4dc7b08bc68cb1f733b7063e3bd68da7bb58e7251818469b91edefc6055bf; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_534660(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/534660"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000b5d6af631537bb5e7ab88c3e7eb6e26d5759ec22eab91519985a5054722c28cc0849190e9d11300089bb8fd74cda03ac84312e02bea72f5d49d4dc7b08bc68cb1f733b7063e3bd68da7bb58e7251818469b91edefc6055bf; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def get_SinAuto_MCMA_expertise_notification_ged(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/ged"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000b5d6af631537bb5e7ab88c3e7eb6e26d5759ec22eab91519985a5054722c28cc0849190e9d11300089bb8fd74cda03ac84312e02bea72f5d49d4dc7b08bc68cb1f733b7063e3bd68da7bb58e7251818469b91edefc6055bf; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.get(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestiongarage_listeDevisDet(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestiongarage/listeDevisDet"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000323ae8a8d6e040a79ebed09899cc9858917519d7a5752bca35f94535706d483608ba2b4e511130008e1ce5965277c9b0078746ea2ddea7436c1b5af61345232c89e42a57efb761d05606c1def65fd7793e5cb6345bda620b; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_listeRapportDefDet(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000089ef952ecf6014225e5323d0bdd43f44f32f430b8a3a54b72a1d96a5e4bdb6d085fdade73113000a1e0103b024c03fd078746ea2ddea7436c1b5af61345232c89e42a57efb761d05606c1def65fd7793e5cb6345bda620b; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_listeMissionExpertByVeh(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/listeMissionExpertByVeh"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/mission",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab2000ba248cd8655e17169e76cad537147502531fcc3d8b2103b477efd90a4bd115e90874873009113000080c5f302309d5b9cfbb8916420299b2c207945bc1e0bcedbac25e5453510122de994cbcb87d3b7f8f65a5b3f79f9c93; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_GED_natureDocuments(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/natureDocuments"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab200029f5ac0f87c1e8b0ed27cfcd3be6e7047f515a1d5e19fd0734cf23c3375f7b7408a8c626fb113000b62334469c2d76ac5d99d0cfcfc78ec300b7c2b8bb0ff981e711d032060398d9e3d1e156549cd74d0f4bdc2f274e8854; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_GED_listDocuments(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/listDocuments"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fa089632cb9eae11618740193f33709adfa63ab2ff28fa5ef0e5a3541af8c6cd857883baffe1970800de760681cd0fb7781cc62cdba5c5183c89da75387c0989ee50c7ff8d3786dd25a96b1b69a42ca3; TS22e9c1cb027=0838c7adb8ab200029f5ac0f87c1e8b0ed27cfcd3be6e7047f515a1d5e19fd0734cf23c3375f7b7408a8c626fb113000b62334469c2d76ac5d99d0cfcfc78ec300b7c2b8bb0ff981e711d032060398d9e3d1e156549cd74d0f4bdc2f274e8854; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_GED_ajouterDocument(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626978fce7e70abf23ee3f4dc32b16c5002caf1b2a44451a0630169cbbc6eef66f3b2bfccd0787adb577077d5820626038a4955b229e4d758022b8b6d1ec669dd94cecaae3a3117bc1aca5c820e8c50f0281; TS22e9c1cb027=0838c7adb8ab20002890b70ca0cb4eeb8b908d82ef317a67fbf6dfe49199fc5590ee22304648319008a2c1ce26113000dc07c70d1e39694325b479265480a8e47f892309e9061171a92ee405c6afd622edc95fa45afaff4596c9dfc506a6a4d5; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestiongarage_garageModifierValDevis(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestiongarage/garageModifierValDevis"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626978fce7e70abf23ee3f4dc32b16c5002caf1b2a44451a0630169cbbc6eef66f3b2bfccd0787adb577077d5820626038a4955b229e4d758022b8b6d1ec669dd94cecaae3a3117bc1aca5c820e8c50f0281; TS22e9c1cb027=0838c7adb8ab2000b3f3859b10abc179d1bba0c09d7d50b0454a6615ed6a7e29168f507c992947bb08ecb5eeab1130005add534dc5cc6db577f67ecc606fcba847f8879eed11cf1967d5cf195adb8b2cb29eda31dd55ea9e6529fb7db4ba1d65; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_notification_getAlerte_CodeAlerte_DB1C2723_9E7C_4711_8B94_F750099E5C46(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/DB1C2723-9E7C-4711-8B94-F750099E5C46"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/notification/alerte/DB1C2723-9E7C-4711-8B94-F750099E5C46",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269f9cb493d5898ce456a2bd3be2e14482bfcf3ebcdc57200ea50857339264f675226a3d8b2e6b9bc216ab1dc250809ab0c5364fcbee2cde7b6c16c46d79d896937d6fd4866a2dbcdffcf9f681ddf3a992d; TS22e9c1cb027=0838c7adb8ab2000e54a7ebe00b176013707d0b6b117a566a664a4a40f9143509bbb9f465588a226081a9cd0461130002b6db369b104ea7a0c0a5f79dfb6151e5e7ad0d40877ca5102d7dd9d3fa67847ec428cfcab0812668c3d4d5ec9503471; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_notification_getAlerte_CodeAlerte_67D9A055_75D1_47CF_A94E_70F4245DE751(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/67D9A055-75D1-47CF-A94E-70F4245DE751"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/notification/alerte/67D9A055-75D1-47CF-A94E-70F4245DE751",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f0162693d27c92670de35beb6af3c2a60326313816756eecc23a3553e51fbb5382b49d72e762d759960b25d9b4a5d77142b96be97cf97159dfc4e70230ecad1dbacfdf3f35dc2aecc46d1a2ad2a2ce69fc8162a; TS22e9c1cb027=0838c7adb8ab2000704c56df8404a0ee6780f49f040e458b2d918f35e93f48a21cf337bf01531a2d089404d767113000cafe299ca83771ae149ac6110e4d666a4ba35dd99bc100032f7e906c58c784232bd3a19546e225addbb70bcb29c2c01b; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_532550(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/532550"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f0162693d27c92670de35beb6af3c2a60326313816756eecc23a3553e51fbb5382b49d72e762d759960b25d9b4a5d77142b96be97cf97159dfc4e70230ecad1dbacfdf3f35dc2aecc46d1a2ad2a2ce69fc8162a; TS22e9c1cb027=0838c7adb8ab2000a107d63cd8ec052b9951701a518cba9f572fb5850d83a1f2dc2d2493f973d9a9081ff0d336113000bc3deee96ff0ad367e53a1e841662b1dfbecea42c5f0079ca7cbb1debcdc6eec2b1ceac13b816f324b6d0b91a867ce2b; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_expertEnregistrerMission(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f0162693d27c92670de35beb6af3c2a60326313816756eecc23a3553e51fbb5382b49d72e762d759960b25d9b4a5d77142b96be97cf97159dfc4e70230ecad1dbacfdf3f35dc2aecc46d1a2ad2a2ce69fc8162a; TS22e9c1cb027=0838c7adb8ab200058f6e9b86ae25310f8f3f876a8f5291eff74d58c0c82845bdc9b2ed83e09746408a7faeb58113000dfff916fb120226784cca184f34c4326c0b02be499d8c9b0d5d2d02307c3cd456b25a3322890b8b43af0445df2e0e677; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_reparation_listeRubriqueFactureDet(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f0162693d27c92670de35beb6af3c2a60326313816756eecc23a3553e51fbb5382b49d72e762d759960b25d9b4a5d77142b96be97cf97159dfc4e70230ecad1dbacfdf3f35dc2aecc46d1a2ad2a2ce69fc8162a; TS22e9c1cb027=0838c7adb8ab2000057dd5ac45955595d064682f7a98c3cc2b7c7fcc7fa4be43df9c0e5d37eff59708c8fd2b14113000f77ef334813f930c608d49908d9624125f62fdfe309658a12a71ab295e043d61cc9571643507e232d0885d52d7259c46; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_createRapportDefDet(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f0162693d27c92670de35beb6af3c2a60326313816756eecc23a3553e51fbb5382b49d72e762d759960b25d9b4a5d77142b96be97cf97159dfc4e70230ecad1dbacfdf3f35dc2aecc46d1a2ad2a2ce69fc8162a; TS22e9c1cb027=0838c7adb8ab20005aaa12c0ab06ad1cc315dcb8796732e6007836f1f93d54dfee32c019dbcb7ef8085e2c0ae21130003216f88f622a6949c29a6cbdb634ba676519eee1d288d79736bfc9c946dbc2dbeb8576c8e5b8801f9c1474f4cb92085d; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_expertCloturerMission(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertCloturerMission"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fee353e93ed29856bd77ed75afd29fca32f4856063ca2a8b668061ee8015333b6b4622f2137731152b9d3e04b023fe3063072892ee8baafdb27061444b85e9343dda55d9f14af1dc3bc88ec1115da943; TS22e9c1cb027=0838c7adb8ab2000f2ad6b5d41054d7ec3aa4d89b0286c14584b315471c89f5cf0869cff0a9c1fb308b537c5b911300064504f2f6216454a7d3cf3767b09c1086ea2f3e30e8d4100b2633eaa6f323dfe8aa52effbe9f710550842c9e115e11ff; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_relance_listeRelances(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/relance/listeRelances"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/relance",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fee353e93ed29856bd77ed75afd29fca32f4856063ca2a8b668061ee8015333b6b4622f2137731152b9d3e04b023fe3063072892ee8baafdb27061444b85e9343dda55d9f14af1dc3bc88ec1115da943; TS22e9c1cb027=0838c7adb8ab20002f9c4041fa9da46b3b9f2881c6693f53cecd402af1f6d88ef7e166e23c91432c08b4c6a9211130004478b253fd6e2dbab30c7f4c9b33513b57854be250f770ba705a2b23ca67df608fbebbd1dd5e79fb8f4bc33209f587b9; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_notification_getAlerte_CodeAlerte_1B03D4D6_6A29_4C93_955E_EF97663862A2(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/1B03D4D6-6A29-4C93-955E-EF97663862A2"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/notification/alerte/1B03D4D6-6A29-4C93-955E-EF97663862A2",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fee353e93ed29856bd77ed75afd29fca32f4856063ca2a8b668061ee8015333b6b4622f2137731152b9d3e04b023fe3063072892ee8baafdb27061444b85e9343dda55d9f14af1dc3bc88ec1115da943; TS22e9c1cb027=0838c7adb8ab2000bc9373d2bb86d92b43561705388595b4cb00a02d935724411e3a3f464b89a503081cf6cbba11300072ae2aee0851507023d064d21806ab832d3bedc188465e089f4760fb1934e866a65002145efcc87f4eb45db5f064f8e3; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_537717(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/537717"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269fee353e93ed29856bd77ed75afd29fca32f4856063ca2a8b668061ee8015333b6b4622f2137731152b9d3e04b023fe3063072892ee8baafdb27061444b85e9343dda55d9f14af1dc3bc88ec1115da943; TS22e9c1cb027=0838c7adb8ab2000607dcd170e6e8ad9060bd500a99efd4770acb315e54051ba85f2ff241af58938087fcbc1e9113000e45c3117a6424b53fa5a5a6561b350c389c08e305b60948b42ec95de0a99c9e07ee42b0da2372bfca05220d11cacd5e1; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_relance_getRelance(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/relance/getRelance/"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/relance",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269197aa2fa080ff427ac1044a869bb48b8c38502a7cbaceb312394a36280f770f70fad1ddfbdc62d28c98c94f9e52f9223618373cd9e89c00e6a322e050121110e373c3d82b39926e889aed84332ac71b0; TS22e9c1cb027=0838c7adb8ab200082938012fdf4e2eba35bb5a7d3a5548773e5270c336b8cbeeac3fbfb4566c14908f8bef36f1130001bb4cd1e9e9c652e11f6aba88eae9a88af3b83da9348c7ffcee812272b5d12b5016e7653258e5139c35fc7c25e7c89ce; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_relance_reponseRelance(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/relance/reponseRelance"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/relance",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269197aa2fa080ff427ac1044a869bb48b8c38502a7cbaceb312394a36280f770f70fad1ddfbdc62d28c98c94f9e52f9223618373cd9e89c00e6a322e050121110e373c3d82b39926e889aed84332ac71b0; TS22e9c1cb027=0838c7adb8ab2000f2eaf0aad67edc203b067cc8287c7445d4e95a99e669eff96d716b7408d530ac08eb79108a113000f8569f5d4d59209c11f6aba88eae9a88af3b83da9348c7ffcee812272b5d12b5016e7653258e5139c35fc7c25e7c89ce; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_539255(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/539255"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269197aa2fa080ff427ac1044a869bb48b8c38502a7cbaceb312394a36280f770f70fad1ddfbdc62d28c98c94f9e52f9223618373cd9e89c00e6a322e050121110e373c3d82b39926e889aed84332ac71b0; TS22e9c1cb027=0838c7adb8ab20003c8973bba88d940d0ef34fdbb04720305595a7c71e4c8fa70125b730a3fcf0750848636828113000fda86acf85738d7c7aed0238cd58b3fe52d5504ee903a48b673a3f44399a8a7ce3c5270d72f9710af73c8d70bd974874; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_notification_getAlerte_CodeAlerte_74A02224_10FC_4945_A144_A36BBDF39C9A(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/getAlerte/CodeAlerte/74A02224-10FC-4945-A144-A36BBDF39C9A"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/notification/notification/alerte/74A02224-10FC-4945-A144-A36BBDF39C9A",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f016269197aa2fa080ff427ac1044a869bb48b8c38502a7cbaceb312394a36280f770f70fad1ddfbdc62d28c98c94f9e52f9223618373cd9e89c00e6a322e050121110e373c3d82b39926e889aed84332ac71b0; TS22e9c1cb027=0838c7adb8ab200019723fe3db7b3f80d4890d09a0a88939c186dc6a8e62efdb73b90bf8573c169d08d9dcca511130001d74af52e458ff784fbd1e86c8324b3243ec177cafe86fe9b8a6be2cc6b8e34e1346f7dc989931d8f972894ddf4e7d0e; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_537593(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/537593"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626955df25da8acb5d4717299c8696a63419d59b40ef7f532ddce8d6b3bb21a6528adea184defac1f05b8c65a253ab2a7c760656f9385cd778f93668f1dab6d94dfe07375b5bcfe892262bde7fd39ec32ee8; TS22e9c1cb027=0838c7adb8ab2000cb952cb0cd11ae0d66bea9841d6cabf52c9bc05f7592905fcebaad84885cbe4d08a47088b511300023d1ed4b93240c0b2cab8df7d93bfff094f4a88e40ed58da560b844d357cfb8c31a29a1ca4501bcff960c39d223138e9; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_relance_createRelance(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/relance/createRelance"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/relance",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626955df25da8acb5d4717299c8696a63419d59b40ef7f532ddce8d6b3bb21a6528adea184defac1f05b8c65a253ab2a7c760656f9385cd778f93668f1dab6d94dfe07375b5bcfe892262bde7fd39ec32ee8; TS22e9c1cb027=0838c7adb8ab2000d779d4907949af1e4c3a4e26f2c206d36c119afc52666ac010e1fb733476f06b085da22d86113000200b581298144057b6209bfe3ee59217264aaef21656e4c464966a64a036d53fb7ef89ce5c1096f8566cdabace77cb74; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_gestion_relance_saveRelance(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/relance/saveRelance"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/relance",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626955df25da8acb5d4717299c8696a63419d59b40ef7f532ddce8d6b3bb21a6528adea184defac1f05b8c65a253ab2a7c760656f9385cd778f93668f1dab6d94dfe07375b5bcfe892262bde7fd39ec32ee8; TS22e9c1cb027=0838c7adb8ab200036dc7db6aab894fc1b59f0369728daab8feb2ee9cb10982fb3878921cf47681c086ce3dd22113000e0d3c2cc52d630f6f6db519d1647053d0eec75a1d46f995c6b0c838b3472db68690630fa2f6616fc5bc2c73df5369210; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text

async def post_SinAuto_MCMA_expertise_gestionExpert_getMission_idMission_535421(payload: dict = None, custom_headers: dict = None):
    url = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/535421"
    headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "accept": "text/html, */*; q=0.01",
    "accept-language": "fr-FR",
    "accept-encoding": "gzip, deflate, br, zstd",
    "referer": "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionexpert/index",
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://sinauto.mamda-mcma.ma",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "connection": "keep-alive",
    "cookie": "TS01f78746=019f01626955df25da8acb5d4717299c8696a63419d59b40ef7f532ddce8d6b3bb21a6528adea184defac1f05b8c65a253ab2a7c760656f9385cd778f93668f1dab6d94dfe07375b5bcfe892262bde7fd39ec32ee8; TS22e9c1cb027=0838c7adb8ab200049e7c1d12200133488f535ef0280463d423f083bf56d7bb153d43e8f05828548081a41c182113000b439d5ee0c9de307cbfe2fc0ab2104b7a226797e5de5a473dcebb9472b6376c760b922f0e6b757000eb75636f7a0a84d; SinAuto_MCMA=pa79v5v856tqg3si1uun2m4271; dtCookieav00743p=v_4_srv_1_sn_P847MK76V7JVB72T29NIDFV38KGTQTDU_app-3Abc3ee5199b8b91f5_1_ol_0_perc_100000_mul_1; rxVisitorav00743p=1787153769877SNHD505V36FUHTJ5F9HKT0OHR01H017V; dtPCav00743p=1$353769875_363h-vFUOPKCNAVARVQFHAHUJUTPFMVKACAPHE-0e0; rxvtav00743p=1787155570430|1787153769878; dtSaav00743p=true%7CC%7C-1%7CSe%20connecter%7C-%7C1787154000490%7C353769875_363%7Chttps%3A%2F%2Fsinauto.mamda-mcma.ma%2FSinAuto_5FMCMA%2F%7C%7C%7C%7C"
}
    if custom_headers:
        headers.update(custom_headers)
        
    async with httpx.AsyncClient(verify=False) as client:
        res = await client.post(
            url, 
            headers=headers, 
            json=payload if payload is not None else None
        )
        try:
            return res.json()
        except Exception:
            return res.text
