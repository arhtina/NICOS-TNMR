from os import environ
description = 'frappy main setup'
group = 'optional'

devices = {
    'se_main':
        device('nicos_sinq.frappy_sinq.devices.FrappyNode',
               uri='pc12694:5000',
               description='main SEC node', unit='',
               prefix=environ.get('SE_PREFIX', ''), auto_create=True, service='main',
        ),
    'timestamp': device('nicos_sinq.linse_nicos.timestamp.Timestamp', description='time, a dummy detector'),
}

startupcode = '''
printinfo("=======================================================================================")
printinfo("Welcome to the NICOS frappy secnode setup for PPMS!")
printinfo(" ")
printinfo("Usage:")
printinfo("  frappy(stick='<stick cfg>')                        # change sample-stick configuration")
printinfo("  frappy(addons='<addon1 cfg>,<addon2 cfg> ...')     # change SE addons")
printinfo("  frappy(stick=None)                                 # remove stick")
printinfo("  frappy(addons=None)                                # remove addons")
printinfo("=======================================================================================")
SetDetectors(timestamp)
'''
